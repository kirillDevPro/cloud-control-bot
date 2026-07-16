"""Dependency Injection container for managing the application's dependencies.

Provides:
- Centralized construction of all components
- Correct initialization order
- Graceful shutdown in reverse order
- A single object that can be passed to startup, tasks, handlers, and shutdown
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from multiprocessing import Queue
from multiprocessing.managers import DictProxy
from typing import TYPE_CHECKING

import httpx
from aiogram import Bot, Dispatcher

if TYPE_CHECKING:
    from .config import Settings
    from .monitoring import PingManager
    from .providers.manager import ProviderManager
    from .storage import BalanceRepository, ServersRepository, SqliteStatisticsRepository

logger = logging.getLogger(__name__)


@dataclass
class ApplicationContainer:
    """
    Application dependency container.

    Holds all components required for the application to run. The builder creates
    these components in dependency order; shutdown closes them in reverse order.

    Attributes:
        settings: Application configuration.
        servers_repo: Servers repository.
        stats_repo: Statistics repository (SQLite).
        balance_repo: Balance history repository.
        provider_manager: Provider manager.
        ping_manager: Ping monitoring manager.
        http_client: Shared httpx client for HTTP service checks (owned here so a
            supervisor restart of the checks task reuses one pool instead of leaking one).
        bot: Telegram bot.
        dispatcher: aiogram dispatcher.
    """

    settings: "Settings"
    servers_repo: "ServersRepository"
    stats_repo: "SqliteStatisticsRepository"
    balance_repo: "BalanceRepository"
    provider_manager: "ProviderManager"
    ping_manager: "PingManager"
    http_client: httpx.AsyncClient
    bot: Bot
    dispatcher: Dispatcher

    @property
    def ping_results_queue(self) -> Queue:
        """Return the IPC queue that carries ping results from workers.

        Returns:
            Queue: Multiprocessing queue owned by PingManager.
        """
        return self.ping_manager.ping_results_queue

    @property
    def shared_state(self) -> DictProxy:
        """Return the shared server-state mapping used by workers and the bot.

        Returns:
            DictProxy: Manager-backed mapping keyed by server composite key.
        """
        return self.ping_manager.shared_state

    @property
    def admin_ids(self) -> list[int]:
        """Return configured administrator IDs.

        Returns:
            list[int]: Telegram user IDs allowed to administer the bot.
        """
        return self.settings.get_admin_ids_list()

    async def shutdown(self) -> None:
        """
        Gracefully shut down all components in reverse order.

        Order:
        1. Worker processes (PingManager)
        2. Providers (HTTP sessions)
        3. Shared service-check HTTP client
        4. Bot (Telegram session)
        5. Statistics DB connection (SQLite)

        Returns:
            None.
        """
        logger.info("Container shutdown started...")

        # 1. Stop worker processes
        if self.ping_manager:
            try:
                self.ping_manager.shutdown_all(timeout=30)
                logger.debug("PingManager workers stopped")
            except Exception as e:
                logger.error(f"Error stopping PingManager: {e}", exc_info=True)

        # 2. Close providers (HTTP sessions)
        if self.provider_manager:
            try:
                await self.provider_manager.close_all()
                logger.debug("Provider sessions closed")
            except Exception as e:
                logger.error(f"Error closing providers: {e}", exc_info=True)

        # 3. Close the shared service-check HTTP client
        if self.http_client:
            try:
                await self.http_client.aclose()
                logger.debug("Service-check HTTP client closed")
            except Exception as e:
                logger.error(f"Error closing service-check HTTP client: {e}", exc_info=True)

        # 4. Close the bot session
        if self.bot:
            try:
                await self.bot.session.close()
                logger.debug("Bot session closed")
            except Exception as e:
                logger.error(f"Error closing bot session: {e}", exc_info=True)

        # 5. Close the statistics DB connection (the final batch flush already ran
        #    during background-task cancellation, before container shutdown)
        if self.stats_repo:
            try:
                self.stats_repo.close()
                logger.debug("Statistics DB connection closed")
            except Exception as e:
                logger.error(f"Error closing statistics DB: {e}", exc_info=True)

        logger.info("Container shutdown complete")


class ContainerBuilder:
    """Builder for constructing an ApplicationContainer."""

    @staticmethod
    async def build(settings: "Settings") -> ApplicationContainer:
        """
        Build and initialize all application components.

        Initialization order:
        1. Repositories and the callback/language/runtime/check-config stores
        2. Shared HTTP service-check client
        3. ProviderManager + Providers
        4. PingManager
        5. Bot + Dispatcher

        Args:
            settings: Loaded configuration.

        Returns:
            ApplicationContainer: A fully initialized container.

        Raises:
            Exception: If a critical component fails to initialize.
        """
        from .bot import create_bot, create_dispatcher
        from .monitoring import PingManager
        from .providers.manager import ProviderManager
        from .storage import BalanceRepository, ServersRepository, SqliteStatisticsRepository

        # 1. Repositories
        logger.debug("Initializing repositories...")
        servers_repo = ServersRepository(settings.get_servers_file())
        stats_repo = SqliteStatisticsRepository(
            settings.get_statistics_db_file(),
            retention_days=settings.STATS_RETENTION_DAYS,
        )
        balance_repo = BalanceRepository(settings.get_balance_history_file())

        # Point the callback-data cache DB at the configured data dir (and init it)
        # so it lives next to the other data files regardless of the working dir.
        from .bot.utils.callback_data import init_callback_cache

        init_callback_cache(settings.DATA_DIR)

        # Point the per-user language store at the configured data dir and load it,
        # so language preferences live next to the other data files and are available
        # to the language middleware and per-recipient notification rendering.
        from .bot.i18n import init_language_store

        init_language_store(settings.DATA_DIR)

        # Load the runtime-mutable global settings (low-balance alert threshold +
        # on/off switch the admin changes from the Settings menu), seeding the
        # threshold from the configured default until it is overridden in-bot.
        from .storage.runtime_settings import init_runtime_settings

        init_runtime_settings(
            settings.get_runtime_settings_file(),
            default_threshold=settings.BALANCE_THRESHOLD,
        )

        # Load per-server service-check definitions (TCP/HTTP/SSL checks the admin
        # configures from chat), read each cycle by the service_checks background task.
        from .storage.service_checks_store import init_service_checks_store

        init_service_checks_store(settings.get_service_checks_file())

        # Shared HTTP client for service checks (HTTP endpoint checks). Owned by the
        # container so a supervisor restart of the checks task reuses this pool rather
        # than leaking one per restart; per-request timeouts are set at each check.
        http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
            # Default OFF to match the check layer's invariant: every HTTP check follows
            # redirects MANUALLY (revalidating each hop's host through resolve_target), so the
            # shared client must never silently auto-follow a redirect into a rejected address.
            follow_redirects=False,
        )

        # 2. Providers
        logger.debug("Initializing providers...")
        provider_manager = ProviderManager()
        await ContainerBuilder._init_providers(settings, provider_manager)

        # 3. PingManager
        logger.debug("Initializing PingManager...")
        ping_manager = PingManager(servers_repo=servers_repo, settings=settings)

        # 4. Bot + Dispatcher
        logger.debug("Initializing Telegram bot...")
        bot = create_bot(settings)
        dispatcher = create_dispatcher(settings)

        logger.info("Container initialized successfully")

        return ApplicationContainer(
            settings=settings,
            servers_repo=servers_repo,
            stats_repo=stats_repo,
            balance_repo=balance_repo,
            provider_manager=provider_manager,
            ping_manager=ping_manager,
            http_client=http_client,
            bot=bot,
            dispatcher=dispatcher,
        )

    @staticmethod
    async def _init_providers(
        settings: "Settings",
        manager: "ProviderManager",
    ) -> None:
        """
        Initialize providers from configurations auto-discovered in the environment.

        Provider configurations are obtained via settings.get_provider_configs(),
        which auto-discovers providers from environment variables. For each
        discovered alias:
        1. Read its ProviderConfig from settings.
        2. Read the credentials from environment variables (AWS uses
           access_key_id + secret_access_key, others use api_key).
        3. Create the provider via ProviderFactory.
        4. Register it in the ProviderManager.

        Aliases with missing credentials are skipped with a warning, and
        per-provider initialization errors are logged without aborting the rest.

        Args:
            settings: Application configuration.
            manager: Provider manager to register providers into.

        Returns:
            None.
        """
        from .models.provider import ProviderType
        from .providers import ProviderFactory

        # Get provider configurations auto-discovered from the environment
        provider_configs = settings.get_provider_configs()

        if not provider_configs:
            logger.warning(
                "No providers discovered from environment variables "
                "(expected HETZNER_*_API_KEY / VULTR_*_API_KEY / "
                "AWS_*_ACCESS_KEY_ID + AWS_*_SECRET_ACCESS_KEY)"
            )
            return

        for alias, config in provider_configs.items():
            try:
                if config.type == ProviderType.AWS:
                    # AWS requires access_key_id + secret_access_key
                    credentials = settings.get_provider_aws_credentials(alias)
                    if not credentials:
                        logger.warning(
                            f"Skipping AWS provider '{alias}': missing credentials "
                            f"(AWS_{alias.upper()}_ACCESS_KEY_ID, "
                            f"AWS_{alias.upper()}_SECRET_ACCESS_KEY)"
                        )
                        continue

                    access_key_id, secret_access_key = credentials
                    provider = ProviderFactory.create(
                        config=config,
                        access_key_id=access_key_id,
                        secret_access_key=secret_access_key,
                    )
                else:
                    # Vultr, Hetzner and others use api_key
                    api_key = settings.get_provider_api_key(alias)
                    if not api_key:
                        expected_env_var = f"{alias.upper()}_API_KEY"
                        logger.warning(
                            f"Skipping provider '{alias}': missing API key ({expected_env_var})"
                        )
                        continue

                    provider = ProviderFactory.create(config=config, api_key=api_key)

                manager.register_provider(alias, provider, config)
                logger.debug(f"Provider '{alias}' ({config.type.value}) initialized")

            except Exception as e:
                logger.error(
                    f"Failed to initialize provider '{alias}': {e}",
                    exc_info=True,
                )

        # Log the final state
        count = manager.get_provider_count()
        if count == 0:
            logger.warning("No providers were successfully initialized!")
        else:
            aliases = manager.get_all_aliases()
            logger.info(f"Initialized {count} provider(s): {', '.join(aliases)}")
