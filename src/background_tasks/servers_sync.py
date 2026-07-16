"""Background task that automatically synchronizes servers with provider APIs."""

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from aiogram import Bot

from ..storage import ServersRepository, SqliteStatisticsRepository
from ..exceptions import is_transient_error
from .ping_processor import forget_server
from .service_checks import forget_server_checks
from ..bot.notifications import (
    render_error_message,
    send_server_added_notification,
    send_server_removed_notification,
    send_critical_error_notification,
    send_provider_outage_notification,
    send_provider_recovered_notification,
)

logger = logging.getLogger(__name__)

# How many CONSECUTIVE failed provider checks must accumulate before a
# transient failure (5xx/timeout/rate-limit) is considered a sustained outage
# and the administrator is notified. Persistent errors (auth/permissions) alert
# immediately.
OUTAGE_ALERT_THRESHOLD = 3


async def servers_sync_task(
    bot: Bot,
    provider_manager: Any,  # ProviderManager
    servers_repo: ServersRepository,
    stats_repo: SqliteStatisticsRepository,
    ping_manager: Any,  # PingManager
    admin_ids: list[int],
    sync_interval: int = 1800,
    heartbeat: Callable[[], None] = lambda: None,
) -> None:
    """
    Background task that automatically synchronizes servers with provider APIs.

    Runs in an infinite loop at the given interval and:
    1. Fetches the current server list from every provider
    2. Synchronizes it with local storage (add/remove/update)
    3. Manages monitoring worker processes (start/stop)
    4. Sends notifications to administrators about changes
    5. Clears ping and service-check statistics plus in-memory alert/schedule state for
       removed servers, while preserving their persisted check configuration

    Provider availability alerting is debounced: transient failures
    (5xx/timeout/rate-limit) only alert once they become a sustained outage
    (>= OUTAGE_ALERT_THRESHOLD consecutive failures), while persistent errors
    (auth/permissions) alert immediately. A recovery notification is sent when a
    provider with an open incident responds again. Per-alias alert state lives in
    memory across loop iterations.

    Args:
        bot: aiogram Bot instance used to send messages.
        provider_manager: Manager of all cloud providers (ProviderManager).
        servers_repo: Server repository.
        stats_repo: SQLite statistics repository.
        ping_manager: Manager of monitoring worker processes (PingManager).
        admin_ids: List of administrator IDs to notify.
        sync_interval: Synchronization interval in seconds (default 1800 = 30 minutes).
        heartbeat: Called once per loop iteration so the supervisor can detect a stall.
            Defaults to a no-op for standalone use/tests.

    Returns:
        None.

    Raises:
        asyncio.CancelledError: Re-raised on cancellation so the task can be
            shut down gracefully.
        Exception: Re-raised on an unrecoverable error that escapes the inner
            per-cycle handling.
    """
    # Provider availability alert state (persists across loop iterations):
    consecutive_failures: dict[str, int] = {}  # consecutive failed checks per alias
    # alias -> kind of the open incident ("transient" | "persistent"); a missing
    # key means no alert is currently open. The kind drives deduplication and the
    # transient -> persistent escalation (auth matters more than a prolonged 5xx).
    incident_kind: dict[str, str] = {}

    try:
        while True:
            heartbeat()  # progress beat at the top of every loop iteration
            # Wait until the next synchronization
            await asyncio.sleep(sync_interval)

            try:
                # Fetch all providers
                providers_dict = provider_manager.get_all_providers()

                if not providers_dict:
                    logger.warning("No providers available for synchronization")
                    continue

                # Fetch servers from all providers in parallel
                provider_tasks = []
                alias_order = []  # Keep the order to match results back to aliases
                for alias, (provider, config) in providers_dict.items():
                    provider_tasks.append(provider.get_servers())
                    alias_order.append(alias)

                # Await results, capturing exceptions instead of raising
                results = await asyncio.gather(*provider_tasks, return_exceptions=True)

                # Collect all servers, handling errors
                all_servers: list[Any] = []
                successful_aliases: set[str] = set()

                for idx, alias in enumerate(alias_order):
                    provider, config = providers_dict[alias]
                    result = results[idx]

                    provider_label = getattr(config, "display_name", "") or alias.upper()

                    if isinstance(result, Exception):
                        logger.error(
                            f"Failed to fetch servers from {alias}: {result}",
                            exc_info=result,
                        )

                        failures = consecutive_failures.get(alias, 0) + 1
                        consecutive_failures[alias] = failures

                        if is_transient_error(result):
                            # Transient failure (5xx/timeout/rate-limit): self-healing.
                            # Alert only once it becomes sustained, and only once.
                            # If an incident (of any kind) is already open for this
                            # alias, stay silent.
                            if failures >= OUTAGE_ALERT_THRESHOLD and alias not in incident_kind:
                                incident_kind[alias] = "transient"
                                await send_provider_outage_notification(
                                    bot=bot,
                                    admin_ids=admin_ids,
                                    provider_label=provider_label,
                                    duration_seconds=failures * sync_interval,
                                    failures=failures,
                                    last_error=result,
                                )
                        elif incident_kind.get(alias) != "persistent":
                            # Persistent error (auth/permissions): requires manual
                            # intervention, so alert immediately. Deduplicated by
                            # incident kind; escalating an already-open transient
                            # incident to persistent breaks the silence (it is
                            # important to report the auth issue).
                            incident_kind[alias] = "persistent"
                            await send_critical_error_notification(
                                bot=bot,
                                admin_ids=admin_ids,
                                title_key="alert.provider_api.title",
                                title_kwargs={"provider": provider_label},
                                body=render_error_message(
                                    "alert.servers_fetch_failed.body", result
                                ),
                            )
                        continue

                    # result is guaranteed to be List[Server] here
                    if isinstance(result, list):
                        # Provider responded: close any open incident for it.
                        if alias in incident_kind:
                            incident_kind.pop(alias, None)
                            await send_provider_recovered_notification(
                                bot=bot,
                                admin_ids=admin_ids,
                                provider_label=provider_label,
                                duration_seconds=consecutive_failures.get(alias, 0) * sync_interval,
                            )
                        consecutive_failures[alias] = 0

                        # Set provider_alias on each server
                        for server in result:
                            if not server.provider_alias:
                                server.provider_alias = alias
                        all_servers.extend(result)
                        successful_aliases.add(alias)

                # If no provider responded, skip this synchronization
                if not successful_aliases:
                    logger.error(
                        "Failed to fetch servers from all providers, skipping synchronization"
                    )
                    continue

                # Synchronize with local storage.
                # Pass successful_aliases so servers of unavailable providers are not removed.
                sync_result = servers_repo.sync_with_api_servers(
                    all_servers,
                    successful_aliases=successful_aliases,
                )

                added_servers = sync_result["added_servers"]
                removed_servers = sync_result["removed_servers"]
                ip_changed_servers = sync_result.get("ip_changed_servers", [])

                # Log information about servers whose removal was skipped
                skipped_count = sync_result.get("skipped_removal_count", 0)
                skipped_aliases = sync_result.get("skipped_aliases", set())
                if skipped_count > 0:
                    logger.info(
                        f"Sync: skipped removal of {skipped_count} servers from unavailable "
                        f"providers: {list(skipped_aliases)}"
                    )

                # Process added servers
                for server in added_servers:
                    composite_key = server.composite_key

                    # Start monitoring only if the server is monitorable. AWS sets
                    # enabled=False for instances with no pingable public IP — those
                    # are recorded but not pinged (else they'd report false offline).
                    if not server.enabled:
                        logger.info(
                            f"New server {server.name} ({composite_key}) added but not "
                            f"monitored (no pingable public IP)"
                        )
                        continue

                    # Start monitoring for the new server
                    try:
                        ping_manager.add_server_monitoring(composite_key)
                        logger.info(f"New server: {server.name} ({composite_key})")
                    except Exception as e:
                        logger.error(
                            f"Failed to start monitoring for {composite_key}: {e}",
                            exc_info=True,
                        )

                    # Send a notification about the new server
                    try:
                        await send_server_added_notification(
                            bot=bot,
                            admin_ids=admin_ids,
                            server_name=server.name,
                            server_ip=server.ip,
                            provider_name=server.provider.value,
                            region=server.region,
                        )
                    except Exception as e:
                        logger.error(f"Failed to send notification for added server: {e}")

                # Process removed servers
                for server in removed_servers:
                    composite_key = server.composite_key

                    # Stop monitoring
                    try:
                        ping_manager.remove_server_monitoring(composite_key)
                        logger.info(f"Removed server: {server.name} ({composite_key})")
                    except Exception as e:
                        logger.error(
                            f"Failed to stop monitoring for {composite_key}: {e}",
                            exc_info=True,
                        )

                    # Clear statistics
                    try:
                        stats_repo.clear_server_history(composite_key)
                    except Exception as e:
                        logger.error(
                            f"Failed to clear statistics for {composite_key}: {e}",
                            exc_info=True,
                        )

                    # Drop the removed server's per-server notification state (anti-leak).
                    forget_server(composite_key)
                    # Drop the removed server's in-memory service-check alert/schedule
                    # state. Deliberately NOT deleting its persisted check config: a
                    # provider returning an erroneous empty list must not vaporize a
                    # user's hand-built checks (they resume if the server returns).
                    forget_server_checks(composite_key)

                    # Send a removal notification
                    try:
                        await send_server_removed_notification(
                            bot=bot,
                            admin_ids=admin_ids,
                            server_name=server.name,
                            server_ip=server.ip,
                            provider_name=server.provider.value,
                        )
                    except Exception as e:
                        logger.error(f"Failed to send notification for removed server: {e}")

                # Process servers whose IP changed (critical for monitoring)
                for server, old_ip in ip_changed_servers:
                    composite_key = server.composite_key

                    try:
                        if server.enabled:
                            # Restart the worker against the new IP (also (re)starts
                            # a server that regained a pingable IP — restart_worker
                            # handles the "no running worker" case).
                            ping_manager.restart_worker(
                                composite_key, reason=f"IP changed: {old_ip} -> {server.ip}"
                            )
                            logger.info(f"IP changed: {server.name} {old_ip} -> {server.ip}")
                        else:
                            # Became unmonitorable (e.g. AWS lost its public IP):
                            # stop the worker instead of pinging an unreachable
                            # address. Safe no-op if no worker is running.
                            ping_manager.remove_server_monitoring(composite_key)
                            logger.info(
                                f"Server {server.name} ({composite_key}) no longer has a "
                                f"pingable IP ({old_ip} -> {server.ip}); monitoring stopped"
                            )
                    except Exception as e:
                        logger.error(
                            f"Failed to update monitoring for {composite_key} after IP change: {e}",
                            exc_info=True,
                        )

            except Exception as e:
                logger.error(f"Error in servers sync cycle: {e}", exc_info=True)
                # Keep running even after an error

    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error(f"Critical error in servers sync task: {e}", exc_info=True)
        raise
