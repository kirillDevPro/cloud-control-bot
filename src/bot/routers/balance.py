"""Balance router for provider balances, history, and settings views."""

import logging

from aiogram import F, Router
from aiogram.types import Message, CallbackQuery

from ...storage.balance import BalanceRepository
from ...providers.manager import ProviderManager
from ..filters import MainMenuButton
from ..i18n import _
from ..keyboards import (
    get_balance_main_keyboard,
    get_balance_history_keyboard,
    get_balance_provider_keyboard,
)
from ..utils import safe_edit_message, handle_telegram_errors, show_screen
from ..formatters import (
    collect_provider_balances,
    format_balance_main,
    format_balance_history,
    format_balance_provider_detail,
)

logger = logging.getLogger(__name__)

balance_router = Router(name="balance")


@balance_router.message(MainMenuButton("menu.balance"))
async def cmd_balance(
    message: Message, balance_repo: BalanceRepository, provider_manager: ProviderManager
) -> None:
    """
    Handle the balance reply-keyboard button.

    Displays a summary of balances across all providers through
    ``show_screen`` so it becomes this chat's single tracked live section
    screen. The user's tap message is not deleted.

    Args:
        message: Incoming reply-keyboard tap message.
        balance_repo: Repository providing balance history.
        provider_manager: Manager exposing configured providers.

    Returns:
        None.
    """
    # Use the helper to collect balance data
    provider_balances = collect_provider_balances(balance_repo, provider_manager)

    # Format and send as the single live section screen (replaces the previous one)
    text = format_balance_main(provider_balances)
    keyboard = get_balance_main_keyboard(provider_balances)
    await show_screen(message, text, keyboard)


@balance_router.callback_query(F.data.startswith("balance_provider_"))
@handle_telegram_errors
async def callback_balance_provider(
    callback: CallbackQuery,
    balance_repo: BalanceRepository,
    provider_manager: ProviderManager,
) -> None:
    """Handle provider selection and show detailed provider information.

    Args:
        callback: Callback query whose data contains the selected provider
            alias.
        balance_repo: Repository providing balance history and burn-rate
            statistics.
        provider_manager: Manager used to resolve the selected provider.

    Returns:
        None.
    """
    # Extract the provider alias from callback_data (balance_provider_hetzner_prod -> hetzner_prod).
    # removeprefix (not replace) so an alias that embeds "balance_provider_" isn't mangled.
    provider_alias = callback.data.removeprefix("balance_provider_")

    await callback.answer()

    # Look up the provider by alias
    provider = provider_manager.get_provider(provider_alias)
    if not provider:
        await safe_edit_message(callback, _("bal.provider_not_found"), None)
        return

    # Gather provider information
    emoji = provider.get_provider_emoji()
    name = provider.get_provider_display_name()
    supports_balance = provider.supports_balance()

    # Get the latest balance record from history for this alias
    latest_record = balance_repo.get_latest_record(provider_alias=provider_alias)

    # Compute burn-rate statistics via linear regression for this alias
    burn_result = balance_repo.calculate_burn_rate_regression(provider_alias=provider_alias)
    burn_rate = burn_result.burn_rate
    days_left = burn_result.days_left
    trend = burn_result.trend

    # Format the message
    text = format_balance_provider_detail(
        provider_emoji=emoji,
        provider_name=name,
        record=latest_record,
        burn_rate=burn_rate,
        days_left=days_left,
        trend=trend,
        supports_balance=supports_balance,
    )

    # Safely update the message
    await safe_edit_message(callback, text, get_balance_provider_keyboard(provider_alias))


@balance_router.callback_query(F.data.startswith("balance_history"))
@handle_telegram_errors
async def callback_balance_history(
    callback: CallbackQuery,
    balance_repo: BalanceRepository,
    provider_manager: ProviderManager,
) -> None:
    """
    Handle a balance-history callback and show balance history.

    Supported callback_data formats:
    - balance_history:provider_type - provider history over 30 days
    - balance_history_7:provider_type - provider history over 7 days
    - balance_history_30:provider_type - provider history over 30 days
    - balance_history_7 / balance_history_30 - overall history (all providers)

    Args:
        callback: Callback query whose data selects period and optional alias.
        balance_repo: Repository providing recent balance records.
        provider_manager: Manager used to collect provider emoji metadata.

    Returns:
        None.
    """
    # Validate callback_data
    if not callback.data:
        await callback.answer(_("bal.error_empty_data"))
        return

    # Parse callback_data
    # Format: "balance_history[_period][:provider]"
    data_parts = callback.data.split(":")

    # Validate: at most 2 parts (command:provider or just command)
    if len(data_parts) > 2:
        logger.warning(f"Invalid callback_data format: {callback.data}")
        await callback.answer(_("bal.error_data_format"))
        return

    command = data_parts[0]

    # Validate command - must start with balance_history
    if not command.startswith("balance_history"):
        logger.warning(f"Invalid command in callback_data: {command}")
        await callback.answer(_("bal.error_unknown_command"))
        return

    # Extract provider_filter with validation
    provider_filter = None
    if len(data_parts) > 1:
        provider_filter = data_parts[1].strip()
        # An empty provider_filter means None
        if not provider_filter:
            provider_filter = None

    # Determine the period from the command suffix
    # command = "balance_history_7" or "balance_history_30"
    # IMPORTANT: use exact comparison instead of endswith,
    # otherwise a provider_alias containing "_7" (e.g. "aws_7_test") would break the logic
    period = 30  # default
    if command == "balance_history_7":
        period = 7
    elif command == "balance_history_30" or command == "balance_history":
        period = 30

    await callback.answer()

    # Fetch records for the period (all providers or a specific alias)
    records = balance_repo.get_recent_records(days=period, provider_alias=provider_filter)

    # Collect provider emojis keyed by alias
    provider_emojis = {}
    providers = provider_manager.get_all_providers()
    for alias, (provider, config) in providers.items():
        provider_emojis[alias] = provider.get_provider_emoji()

    # Format the message
    text = format_balance_history(records, period, provider_emojis, provider_filter)

    # Safely update the message
    await safe_edit_message(
        callback,
        text,
        get_balance_history_keyboard(period=period, provider_alias=provider_filter),
    )


@balance_router.callback_query(F.data == "balance_back_to_main")
@handle_telegram_errors
async def callback_balance_back_to_main(
    callback: CallbackQuery,
    balance_repo: BalanceRepository,
    provider_manager: ProviderManager,
) -> None:
    """
    Return from a balance subview to the all-providers balance summary.

    Args:
        callback: Callback query from the back button.
        balance_repo: Repository providing balance history.
        provider_manager: Manager exposing configured providers.

    Returns:
        None.
    """
    await callback.answer()

    # Use the helper to collect balance data (removes duplication)
    provider_balances = collect_provider_balances(balance_repo, provider_manager)

    # Format the message
    text = format_balance_main(provider_balances)
    keyboard = get_balance_main_keyboard(provider_balances)

    # Safely update the message
    await safe_edit_message(callback, text, keyboard)
