"""
Application entry point for the Telegram bot and monitoring system.

Initializes all system components through the DI container:
- Loading settings
- Initializing repositories, providers, PingManager
- Starting worker processes
- Starting supervised background tasks with heartbeat-based stall detection
- Starting the Telegram bot polling loop
- Graceful shutdown on stop
"""

import asyncio
import logging
import sys
from pathlib import Path

# Load .env BEFORE importing settings.
# This is needed so that os.environ contains the variables for get_provider_api_key().
from dotenv import load_dotenv

load_dotenv()

# Add src to the import path
sys.path.insert(0, str(Path(__file__).parent))

from aiogram.types import BotCommand

from src.background_tasks import (
    balance_checker,
    ping_results_processor,
    servers_sync_task,
    workers_health_task,
)
from src.background_tasks.heartbeat import HeartbeatRegistry
from src.background_tasks.supervisor import TaskFactory, supervise_background_tasks
from src.config import get_settings
from src.container import ApplicationContainer, ContainerBuilder
from src.models import Server
from src.storage.runtime_settings import are_balance_alerts_enabled, get_balance_threshold
from src.utils.log_cleaner import log_cleanup_task
from src.utils.logger import configure_third_party_loggers, setup_main_logger

# CRITICAL: Logging is configured AFTER loading settings in main()
# so that LOG_LEVEL from .env can be used.
logger = logging.getLogger(__name__)


# Global container used for graceful shutdown
container: ApplicationContainer | None = None


async def sync_servers_on_startup(app: ApplicationContainer) -> dict | None:
    """
    Synchronize servers from all providers on startup.

    Args:
        app: Application DI container

    Returns:
        dict | None: Error information if all providers are unavailable
    """
    logger.info("Syncing servers from providers...")
    all_servers: list[Server] = []

    # Build tasks for fetching servers in parallel
    provider_tasks = []
    alias_order = []  # Preserve alias order so results can be matched back to providers

    for alias, (provider, config) in app.provider_manager.get_all_providers().items():
        provider_tasks.append(provider.get_servers())
        alias_order.append(alias)

    # Run all requests in parallel
    results = await asyncio.gather(*provider_tasks, return_exceptions=True)

    # Counters to track provider availability
    failed_providers = []
    successful_providers = []

    # Process the results
    for alias, result in zip(alias_order, results):
        # Check for exceptions (Exception, NOT BaseException, for correct shutdown)
        if isinstance(result, Exception):
            logger.error(f"Failed to fetch from {alias}: {result}")
            failed_providers.append(alias)
            continue

        # Validate the result type
        if not isinstance(result, list):
            logger.error(f"Invalid result from {alias}: {type(result).__name__}")
            failed_providers.append(alias)
            continue

        # Set provider_alias for every server
        for server in result:
            if not server.provider_alias:
                server.provider_alias = alias

        # result is guaranteed to be List[Server] here
        all_servers.extend(result)
        successful_providers.append(alias)

    # Update the repository with all servers at once
    if all_servers:
        try:
            sync_stats = app.servers_repo.bulk_update_from_api(all_servers)
            logger.info(
                f"Servers synced: {len(all_servers)} total "
                f"(+{sync_stats['added']}, ~{sync_stats['updated']}, ={sync_stats['unchanged']})"
            )
        except Exception as e:
            logger.error(f"Failed to update servers repository: {e}", exc_info=True)
    else:
        logger.warning("No servers fetched from any provider")

    # Return error information if all providers are unavailable. The admin alert
    # text is localized per recipient at the send site (i18n), so only the failed
    # provider list is returned here.
    if failed_providers and not successful_providers:
        logger.critical(f"All providers unavailable: {', '.join(failed_providers)}")
        return {"failed_providers": ", ".join(failed_providers)}

    return None


async def start_background_tasks(
    app: ApplicationContainer,
    heartbeats: HeartbeatRegistry,
) -> tuple[dict[str, asyncio.Task], dict[str, TaskFactory]]:
    """
    Register background-task factories, run the one-time startup balance check, and
    start the initial task for each.

    Every task is registered as a name -> zero-arg coroutine factory so the task
    supervisor can recreate it after an unexpected crash. The returned task dict and
    factory dict are handed to supervise_background_tasks().

    Args:
        app: Application DI container
        heartbeats: Registry the tasks beat into so the supervisor can detect stalls.

    Returns:
        tuple: (tasks, factories) where tasks maps name -> live asyncio.Task and
            factories maps the same name -> the coroutine factory that produces it.

    Raises:
        Exception: If the critical ping_processor task cannot be created (startup aborts).
    """
    factories: dict[str, TaskFactory] = {}
    tasks: dict[str, asyncio.Task] = {}

    def _start(name: str, factory: TaskFactory, *, critical: bool = False) -> None:
        """Register a task factory and create the initial task.

        Args:
            name: Stable supervised-task name.
            factory: Zero-argument coroutine factory used now and by the supervisor.
            critical: If True, cancel already-started tasks and re-raise startup errors.

        Returns:
            None.

        Raises:
            Exception: Re-raised from asyncio.create_task(factory()) for critical tasks.
        """
        factories[name] = factory
        try:
            tasks[name] = asyncio.create_task(factory(), name=name)
        except Exception as e:
            logger.error(f"Failed to start background task '{name}': {e}", exc_info=True)
            if critical:
                # The processor is critical: without it nothing turns pings into
                # alerts/stats. Cancel whatever started and abort startup.
                for started in tasks.values():
                    started.cancel()
                raise

    # 1. Ping results processor (critical) - started FIRST, before the one-time balance
    #    check, so it is already draining the IPC queue (workers are already pinging)
    #    instead of sitting behind a potentially slow balance API call.
    _start(
        "ping_processor",
        lambda: ping_results_processor(
            bot=app.bot,
            ping_results_queue=app.ping_results_queue,
            shared_state=app.shared_state,
            admin_ids=app.admin_ids,
            servers_repo=app.servers_repo,
            stats_repo=app.stats_repo,
            heartbeat=heartbeats.bound_beat("ping_processor"),
        ),
        critical=True,
    )

    # 2. Balance: one-time startup check then the recurring checker - only for providers
    #    that expose a balance API.
    providers_with_balance = [
        (alias, provider, config)
        for alias, (provider, config) in app.provider_manager.get_all_providers().items()
        if provider.supports_balance()
    ]
    if providers_with_balance:
        # One-time initial balance check (the recurring task waits a full interval before
        # its first check). Runs AFTER ping_processor is live so a slow balance API cannot
        # delay the critical drain.
        logger.info("Initial balance check...")
        for alias, provider, config in providers_with_balance:
            try:
                balance_record = await provider.get_balance()
                if balance_record:
                    if not balance_record.provider_alias:
                        balance_record.provider_alias = alias
                    app.balance_repo.add_record(balance_record)
                    logger.info(f"Balance fetched for {alias}")
            except Exception as e:
                logger.warning(f"Initial balance check failed for {alias}: {e}")

        _start(
            "balance_checker",
            lambda: balance_checker(
                bot=app.bot,
                balance_repo=app.balance_repo,
                provider_manager=app.provider_manager,
                admin_ids=app.admin_ids,
                check_interval=app.settings.BALANCE_CHECK_INTERVAL,
                threshold_getter=get_balance_threshold,
                alerts_enabled_getter=are_balance_alerts_enabled,
                heartbeat=heartbeats.bound_beat("balance_checker"),
            ),
        )

    # 3. Automatic server synchronization
    _start(
        "servers_sync",
        lambda: servers_sync_task(
            bot=app.bot,
            provider_manager=app.provider_manager,
            servers_repo=app.servers_repo,
            stats_repo=app.stats_repo,
            ping_manager=app.ping_manager,
            admin_ids=app.admin_ids,
            sync_interval=app.settings.SERVERS_SYNC_INTERVAL,
            heartbeat=heartbeats.bound_beat("servers_sync"),
        ),
    )

    # 4. Cleanup of old rotated logs
    logs_dir = Path(__file__).parent / "logs"
    _start(
        "log_cleanup",
        lambda: log_cleanup_task(
            logs_dir=logs_dir,
            interval_hours=24,
            heartbeat=heartbeats.bound_beat("log_cleanup"),
        ),
    )

    # 5. Worker health check (restart crashed workers, alert on abandonment, reconcile)
    _start(
        "workers_health",
        lambda: workers_health_task(
            ping_manager=app.ping_manager,
            servers_repo=app.servers_repo,
            bot=app.bot,
            admin_ids=app.admin_ids,
            heartbeat=heartbeats.bound_beat("workers_health"),
        ),
    )

    logger.info(f"Started {len(tasks)} background tasks: {', '.join(tasks)}")
    return tasks, factories


async def stop_background_tasks(tasks: dict[str, asyncio.Task]) -> None:
    """
    Cancel and join all background tasks.

    A task that has ALREADY finished (the supervisor gave up and left a crashed task in
    the dict, or a task crashed between supervisor scans) re-raises its stored exception
    when awaited. That exception is caught and logged here so it can never abort the
    shutdown loop and skip the remaining teardown (most importantly container.shutdown()).

    Args:
        tasks: Dictionary of live (or already-finished) tasks keyed by name.

    Returns:
        None.
    """
    for name, task in tasks.items():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            logger.debug(f"Task {name} cancelled")
        except Exception as e:
            # An already-crashed / given-up task re-raises its stored exception here;
            # swallow it so teardown of the remaining tasks and the container continues.
            logger.error(f"Task {name} ended with error during shutdown: {e}", exc_info=True)


async def main() -> None:
    """Initialize the application, start polling, and coordinate graceful shutdown.

    Builds the DI container, synchronizes provider servers, starts worker processes,
    starts the supervised background-task set, drops pending Telegram updates, and then
    runs aiogram polling until shutdown.

    Raises:
        SystemExit: Exits with status 1 when settings, container construction, or
            critical background-task startup fails.

    Returns:
        None.
    """
    global container

    logger.info("Starting Cloud Server Monitoring Bot...")

    # 1. Load settings
    # IMPORTANT: Logging is configured BEFORE the first use of logger
    try:
        settings = get_settings()

        # Configure logging with the level from settings
        setup_main_logger(log_level=settings.LOG_LEVEL, console_output=True)

        # Configure logging for third-party libraries
        configure_third_party_loggers(level="WARNING")
    except Exception as e:
        # If settings could not be loaded, fall back to the default level
        setup_main_logger(log_level="INFO", console_output=True)
        logger.critical(f"Failed to load settings: {e}", exc_info=True)
        sys.exit(1)

    # 2. Build the container with all dependencies
    try:
        container = await ContainerBuilder.build(settings)
    except Exception as e:
        logger.critical(f"Failed to build application container: {e}", exc_info=True)
        sys.exit(1)

    # 3. Check: at least one provider must be configured
    if container.provider_manager.get_provider_count() == 0:
        logger.critical("No providers configured! Cannot start monitoring.")
        sys.exit(1)

    logger.info(f"Providers: {container.provider_manager.get_provider_count()} initialized")

    # 4. Synchronize servers from all providers
    providers_unavailable_error = await sync_servers_on_startup(container)

    # 5. Start worker processes
    try:
        worker_count = container.ping_manager.start_all_workers()
        logger.info(f"Workers started: {worker_count}")
    except Exception as e:
        logger.error(f"Failed to start worker processes: {e}", exc_info=True)
        # Keep running; workers can be started later

    # 6. Register bot commands, localized per Telegram client language.
    #    The default (English) scope covers every client locale without a specific
    #    set; each additional supported language gets its own descriptions for
    #    clients in that locale. (The /start reply itself uses each user's stored
    #    language, independent of this client-language command menu.)
    try:
        from src.bot.i18n import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES, translate

        def _commands_for(language: str) -> list[BotCommand]:
            """Build bot-command descriptions for one Telegram client language.

            Args:
                language: Language code passed to the explicit translator.

            Returns:
                list[BotCommand]: Commands with descriptions localized for that
                    Telegram client language scope.
            """
            return [
                BotCommand(command="start", description=translate("cmd.start_desc", language)),
                BotCommand(
                    command="language", description=translate("cmd.language_desc", language)
                ),
            ]

        # Default (unscoped) menu in the default language, then a scoped menu for
        # every other supported language — so a new locale is picked up automatically.
        await container.bot.set_my_commands(_commands_for(DEFAULT_LANGUAGE))
        for language in SUPPORTED_LANGUAGES:
            if language != DEFAULT_LANGUAGE:
                await container.bot.set_my_commands(
                    _commands_for(language), language_code=language
                )
        logger.info("Bot commands registered")
    except Exception as e:
        logger.error(f"Failed to register bot commands: {e}", exc_info=True)

    # 7. Send a critical notification if all providers are unavailable
    if providers_unavailable_error:
        from src.bot.notifications import render_message, send_critical_error_notification

        try:
            await send_critical_error_notification(
                bot=container.bot,
                admin_ids=container.admin_ids,
                title_key="alert.providers_unavailable.title",
                body=render_message(
                    "alert.providers_unavailable.body",
                    providers=providers_unavailable_error["failed_providers"],
                ),
            )
        except Exception as e:
            logger.error(f"Failed to send critical notification: {e}")

    # 8. Start background tasks and the supervisor that keeps them alive.
    heartbeats = HeartbeatRegistry()
    try:
        tasks, factories = await start_background_tasks(container, heartbeats)
    except Exception as e:
        logger.critical(f"Failed to start background tasks: {e}", exc_info=True)
        await container.shutdown()
        sys.exit(1)

    # Per-task staleness budgets: max seconds without a heartbeat before the supervisor
    # flags a task as stalled. Sized to ~2x each task's expected cycle so a normal slow
    # cycle never false-alarms; the short-cycle critical tasks get a tight 120s budget.
    staleness_budgets = {
        # ping_processor beats per drained result, so a single slow Telegram send still
        # advances it well within 120s.
        "ping_processor": 120.0,
        # workers_health beats once per cycle; that cycle can legitimately run long during
        # an incident (a burst of abandonment alerts, each with a Telegram flood-control
        # retry per admin), so it gets a generous budget — a genuine wedge still alerts in
        # ~10 min while a slow incident cycle does not false-alarm.
        "workers_health": 600.0,
        "servers_sync": 2 * container.settings.SERVERS_SYNC_INTERVAL + 300.0,
        "balance_checker": 2 * container.settings.BALANCE_CHECK_INTERVAL + 600.0,
        "log_cleanup": 2 * 24 * 3600.0,
    }

    # Supervisor: detects any background task that exits unexpectedly (a crash, not a
    # cancellation) OR stalls (alive but no longer making progress), alerts admins, and
    # recreates crashed tasks. Runs concurrently with polling for the whole process
    # lifetime so a dead or wedged task can never degrade monitoring silently.
    supervisor_shutdown = asyncio.Event()
    supervisor_task = asyncio.create_task(
        supervise_background_tasks(
            tasks,
            factories,
            bot=container.bot,
            admin_ids=container.admin_ids,
            shutdown_event=supervisor_shutdown,
            heartbeats=heartbeats,
            staleness_budgets=staleness_budgets,
        ),
        name="task_supervisor",
    )

    # 9. Drop updates buffered while the bot was down, then start polling.
    # IMPORTANT: aiogram 3.x start_polling has NO skip_updates/drop_pending_updates
    # parameter — passing such a flag only injects it as contextual handler data
    # and does NOT drop the backlog, so a stale destructive callback (e.g. an old
    # stop/reboot tap) would replay on restart. delete_webhook(drop_pending_updates=True)
    # is the correct mechanism (and also clears any stale webhook so getUpdates can't 409).
    # Retry a few times: dropping the backlog is the guard against a stale destructive
    # callback (e.g. an old stop/reboot tap) replaying on restart, so a transient network
    # blip here should not silently skip it. Proceed anyway after the last attempt —
    # failing startup would defeat 24/7 autonomy, and the worst case is one un-dropped
    # backlog (partly covered by the bot-process-local power-op cooldown, empty on a fresh start).
    for attempt in range(1, 4):
        try:
            await container.bot.delete_webhook(drop_pending_updates=True)
            logger.info("Pending updates dropped (delete_webhook)")
            break
        except Exception as e:
            logger.warning(f"Failed to drop pending updates (attempt {attempt}/3): {e}")
            if attempt < 3:
                await asyncio.sleep(2)
    else:
        logger.error(
            "Could not drop pending updates after 3 attempts; starting polling anyway "
            "(a stale callback buffered during downtime may replay once)"
        )

    logger.info("Bot is running (Ctrl+C to stop)")

    try:
        await container.dispatcher.start_polling(
            container.bot,
            servers_repo=container.servers_repo,
            stats_repo=container.stats_repo,
            balance_repo=container.balance_repo,
            shared_state=container.shared_state,
            provider_manager=container.provider_manager,
            settings=container.settings,
        )
    except Exception as e:
        logger.error(f"Error during polling: {e}", exc_info=True)
    finally:
        # Graceful shutdown
        logger.info("Shutting down...")

        # Stop the supervisor FIRST so it does not restart tasks mid-teardown.
        supervisor_shutdown.set()
        supervisor_task.cancel()
        try:
            await supervisor_task
        except asyncio.CancelledError:
            pass

        # Stop background tasks
        await stop_background_tasks(tasks)

        # Stop the container (workers, providers, bot session)
        await container.shutdown()

        logger.info("Shutdown complete")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user (KeyboardInterrupt)")
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
