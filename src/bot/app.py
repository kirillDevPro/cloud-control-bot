"""Factory functions for the Telegram bot and dispatcher."""

import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.types import ErrorEvent

from ..config import Settings
from .middlewares import AdminCheckMiddleware, LanguageMiddleware
from .routers import (
    start_router,
    monitoring_router,
    servers_router,
    balance_router,
    settings_router,
)

logger = logging.getLogger(__name__)


def create_bot(settings: Settings) -> Bot:
    """
    Create and configure a bot instance.

    Args:
        settings: Application settings

    Returns:
        Bot: Configured bot instance
    """
    bot = Bot(
        token=settings.TELEGRAM_BOT_TOKEN,
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML  # vestigial default; sends go via rich (utils/rich.py)
        ),
    )

    logger.info("Bot instance created")
    return bot


async def _on_unhandled_error(event: ErrorEvent) -> None:
    """
    Global fallback for exceptions not handled by a more specific handler.

    Backstops the entry-point message handlers (cmd_start / cmd_monitoring /
    cmd_servers / cmd_balance), which are NOT wrapped by handle_telegram_errors;
    without this, an exception there would surface only in aiogram's internal log
    and the user's tap would appear to do nothing.

    TelegramAPIError from a CALLBACK update is skipped: handle_telegram_errors
    already logs (and re-raises) those for the decorated callback handlers, so
    logging them here too would just duplicate the entry without the handler-name
    context. The message entry-point handlers are NOT decorated, so a
    TelegramAPIError from one of them (e.g. a failed message.answer inside
    show_screen) would otherwise vanish silently; those non-callback updates
    are logged here at WARNING.

    Args:
        event: The aiogram error event (carries .exception and .update).

    Returns:
        None.
    """
    if isinstance(event.exception, TelegramAPIError):
        if event.update.callback_query is None:
            logger.warning(f"TelegramAPIError in an unhandled message update: {event.exception}")
        return
    logger.error(
        f"Unhandled error while processing an update: {event.exception}",
        exc_info=event.exception,
    )


def create_dispatcher(settings: Settings) -> Dispatcher:
    """
    Create and configure the dispatcher.

    Registers middleware and routers in the correct order:
    1. Middleware (MUST come BEFORE routers!)
    2. Routers

    FSM storage is the aiogram default in-memory backend (no ``storage=`` passed):
    fine for the only FSM flow — the short-lived, admin-only custom balance-threshold
    input — whose state is intentionally transient and is re-armed/cleared on the next
    interaction. A bot restart mid-input loses that state harmlessly (the prompt's
    Cancel re-renders cleanly). Switch to a persistent storage only if multi-replica or
    multi-step flows are added.

    Args:
        settings: Application settings

    Returns:
        Dispatcher: Configured dispatcher
    """
    dp = Dispatcher()

    # CRITICAL: Middleware must be registered BEFORE routers!
    admin_ids = settings.get_admin_ids_list()
    logger.info(f"Registering AdminCheckMiddleware with {len(admin_ids)} admin(s)")

    # Create a single middleware instance
    admin_middleware = AdminCheckMiddleware(admin_ids)

    # Register for Message and CallbackQuery
    dp.message.middleware(admin_middleware)
    dp.callback_query.middleware(admin_middleware)

    # Language middleware AFTER admin: resolves the (admin) sender's UI language
    # into the context var + data dict so handlers/keyboards/formatters render in
    # that language. Non-admins are already blocked by AdminCheckMiddleware.
    language_middleware = LanguageMiddleware()
    dp.message.middleware(language_middleware)
    dp.callback_query.middleware(language_middleware)

    # Register routers
    logger.info("Registering routers...")
    dp.include_router(start_router)
    dp.include_router(settings_router)
    dp.include_router(monitoring_router)
    dp.include_router(servers_router)
    dp.include_router(balance_router)
    logger.info(
        "Routers registered: start_router, settings_router, monitoring_router, "
        "servers_router, balance_router"
    )

    # Global fallback error handler (backstops the un-decorated entry-point handlers)
    dp.errors.register(_on_unhandled_error)

    logger.info("Dispatcher created and configured")
    return dp
