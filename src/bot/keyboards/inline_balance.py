"""Inline keyboard builders for balances and provider selection."""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from ...models import Server
from ..i18n import _


def get_balance_main_keyboard(provider_balances: dict[str, dict]) -> InlineKeyboardMarkup:
    """
    Return an inline keyboard for the main balance screen.

    Buttons are sorted: providers with an available balance first, then the
    unavailable ones (supports_balance=False).

    Args:
        provider_balances: Provider data dictionary from collect_provider_balances()
            {alias: {"name": str, "supports_balance": bool, ...}}.

    Returns:
        InlineKeyboardMarkup: Keyboard with the provider selection buttons.
    """
    # Split the providers into two groups
    available: list[tuple[str, str]] = []  # supports_balance=True
    unavailable: list[tuple[str, str]] = []  # supports_balance=False

    for alias, data in provider_balances.items():
        name = data["name"]
        if data["supports_balance"]:
            available.append((alias, name))
        else:
            unavailable.append((alias, name))

    # Combine: available first, then unavailable
    sorted_providers = available + unavailable

    # Build buttons, 2 per row
    keyboard: list[list[InlineKeyboardButton]] = []
    provider_buttons: list[InlineKeyboardButton] = []

    for alias, name in sorted_providers:
        provider_buttons.append(
            InlineKeyboardButton(
                text=f"🌍 {name}",
                callback_data=f"balance_provider_{alias}",
            )
        )

        # Append a row once 2 buttons have accumulated
        if len(provider_buttons) == 2:
            keyboard.append(provider_buttons)
            provider_buttons = []

    # Append the remaining buttons (if the count is odd)
    if provider_buttons:
        keyboard.append(provider_buttons)

    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_balance_history_keyboard(
    period: int = 30, provider_alias: str | None = None
) -> InlineKeyboardMarkup:
    """
    Return an inline keyboard for the balance history screen.

    Args:
        period: Current period in days (7 or 30).
        provider_alias: Provider alias to filter by (hetzner_prod, vultr_main, etc.).
                        If None, shows the history of all providers.

    Returns:
        InlineKeyboardMarkup: Keyboard with period toggles and a "Back" button.
    """
    keyboard = []

    # Build the provider suffix for callback_data
    provider_suffix = f":{provider_alias}" if provider_alias else ""

    # Period toggle buttons
    period_buttons = []

    # "7 days" button
    if period == 7:
        # Current period - shown as selected
        period_buttons.append(
            InlineKeyboardButton(
                text=f"• {_('kb.period_7')} •", callback_data=f"balance_history_7{provider_suffix}"
            )
        )
    else:
        period_buttons.append(
            InlineKeyboardButton(
                text=_("kb.period_7"), callback_data=f"balance_history_7{provider_suffix}"
            )
        )

    # "30 days" button
    if period == 30:
        # Current period - shown as selected
        period_buttons.append(
            InlineKeyboardButton(
                text=f"• {_('kb.period_30')} •",
                callback_data=f"balance_history_30{provider_suffix}",
            )
        )
    else:
        period_buttons.append(
            InlineKeyboardButton(
                text=_("kb.period_30"), callback_data=f"balance_history_30{provider_suffix}"
            )
        )

    keyboard.append(period_buttons)

    # "Back" button - returns to the provider or to the main screen
    if provider_alias:
        back_callback = f"balance_provider_{provider_alias}"
    else:
        back_callback = "balance_back_to_main"

    keyboard.append([InlineKeyboardButton(text=_("common.back"), callback_data=back_callback)])

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_balance_provider_keyboard(provider_alias: str) -> InlineKeyboardMarkup:
    """
    Return an inline keyboard for the provider detail view.

    Args:
        provider_alias: Provider alias (hetzner_prod, vultr_main, etc.).

    Returns:
        InlineKeyboardMarkup: Keyboard with "History" and "Back" buttons.
    """
    keyboard = [
        [InlineKeyboardButton(text=_("kb.history"), callback_data=f"balance_history:{provider_alias}")],
        [InlineKeyboardButton(text=_("common.back"), callback_data="balance_back_to_main")],
    ]

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_provider_selection_keyboard(servers: list[Server]) -> InlineKeyboardMarkup:
    """
    Return an inline keyboard for selecting a provider.

    Shows providers grouped by provider_alias. Each button contains the provider
    alias and the number of servers.

    Args:
        servers: List of all servers.

    Returns:
        InlineKeyboardMarkup: Keyboard with the provider buttons.
    """
    # Count servers per provider_alias (effective_alias accounts for legacy)
    alias_counts: dict[str, int] = {}
    for server in servers:
        alias = server.effective_alias
        alias_counts[alias] = alias_counts.get(alias, 0) + 1

    # Build the keyboard
    keyboard = []

    # Add a button for each alias that has servers
    for alias, count in sorted(alias_counts.items(), key=lambda x: x[1], reverse=True):
        if count > 0:
            # Format the label: hetzner_prod -> HETZNER_PROD
            button_text = f"☁️ {alias.upper()} ({count})"
            keyboard.append(
                [
                    InlineKeyboardButton(
                        text=button_text,
                        callback_data=f"provider_select_{alias}",
                    )
                ]
            )

    return InlineKeyboardMarkup(inline_keyboard=keyboard)
