"""Formatters for the balance router."""

from ...storage.balance import (
    BalanceRecord,
    BalanceRepository,
    PostpaidBalanceRecord,
    PrepaidBalanceRecord,
)
from ...providers.manager import ProviderManager
from ..i18n import _, plural
from ..utils.rich import blocks, stack
from .common import format_days_as_period, esc


def collect_provider_balances(
    balance_repo: BalanceRepository,
    provider_manager: ProviderManager,
) -> dict[str, dict]:
    """
    Collect balance information for all providers.

    Removes duplication between cmd_balance and callback_balance_back_to_main.

    Args:
        balance_repo: Balance repository
        provider_manager: Provider manager

    Returns:
        Dict with information about each provider:
        {
            "hetzner_prod": {
                "emoji": "[H]",
                "name": "Hetzner (prod)",
                "balance": 123.45,
                "supports_balance": True,
                "billing_model": "prepaid",
                "pending_charges": 21.06,
                "monthly_costs": None,
            },
            ...
        }
    """
    provider_balances = {}
    providers = provider_manager.get_all_providers()

    # providers returns dict[str, tuple[BaseProvider, ProviderConfig]]
    for alias, (provider, config) in providers.items():
        # Look up the latest balance by provider alias.
        latest_record = balance_repo.get_latest_record(provider_alias=alias)

        # Determine charges depending on the record type
        pending_charges: float | None = None
        monthly_costs: float | None = None

        if latest_record is not None:
            if isinstance(latest_record, PrepaidBalanceRecord):
                pending_charges = latest_record.pending_charges
            elif isinstance(latest_record, PostpaidBalanceRecord):
                monthly_costs = latest_record.monthly_costs

        provider_balances[alias] = {
            "emoji": provider.get_provider_emoji(),
            "name": provider.get_provider_display_name(),
            "balance": latest_record.display_value if latest_record else None,
            "supports_balance": provider.supports_balance(),
            "billing_model": provider.get_billing_model().value,
            "pending_charges": pending_charges,
            "monthly_costs": monthly_costs,
        }

    return provider_balances


# On-screen provider markers: the ASCII log emoji ([H]/[V]/[A]) is mapped to a
# colored circle for the rich UI. The ASCII form is kept for logs/test output
# (project convention); only the screen presentation is upgraded.
_UI_PROVIDER_EMOJI: dict[str, str] = {"[H]": "🔴", "[V]": "🔵", "[A]": "🟠"}


def _ui_emoji(marker: str) -> str:
    """Map a provider's ASCII log marker to a colored UI circle.

    Args:
        marker: The provider's ASCII emoji ("[H]" / "[V]" / "[A]"), or any other
            value (e.g. a legacy emoji already stored).

    Returns:
        str: The matching colored circle, or a cloud fallback for an unknown
            marker.
    """
    return _UI_PROVIDER_EMOJI.get(marker, "☁️")


def format_balance_main(provider_balances: dict) -> str:
    """
    Format the main balance screen - a summary across all providers.

    Groups by categories:
    1. Available funds (prepaid balances)
    2. Charges for the current month
    3. Unavailable providers

    Args:
        provider_balances: Dict with provider balances

    Returns:
        str: Formatted message in the active language
    """
    if not provider_balances:
        return blocks(_("bal.main_title"), _("bal.no_providers"), _("bal.add_api_keys"))

    # Group providers by category
    available_balances: list[tuple[str, str, float]] = []  # (emoji, name, balance)
    postpaid_providers: list[tuple[str, str]] = []  # (emoji, name) - for the balances section
    monthly_expenses: list[tuple[str, str, float]] = []  # (emoji, name, amount)
    unavailable: list[tuple[str, str]] = []  # (emoji, name)

    for provider_data in provider_balances.values():
        emoji = provider_data["emoji"]
        name = provider_data["name"]
        balance = provider_data["balance"]
        supports_balance = provider_data["supports_balance"]
        billing_model = provider_data.get("billing_model", "prepaid")
        pending_charges = provider_data.get("pending_charges")
        monthly_costs = provider_data.get("monthly_costs")

        if not supports_balance:
            # Provider does not support the balance API
            unavailable.append((emoji, name))
        elif billing_model == "postpaid":
            # Postpaid (AWS) - no balance, only charges
            postpaid_providers.append((emoji, name))
            if monthly_costs is not None:
                monthly_expenses.append((emoji, name, monthly_costs))
        elif balance is not None:
            # Prepaid (Vultr) - has a balance
            available_balances.append((emoji, name, balance))
            if pending_charges is not None and pending_charges > 0:
                monthly_expenses.append((emoji, name, pending_charges))

    sections: list[str] = [_("bal.main_title")]

    # Section 1: Available funds as compact lines (provider: balance).
    if available_balances or postpaid_providers:
        funds_lines = [
            f"{_ui_emoji(emoji)} {esc(name)}: <b>${balance:,.2f}</b>"
            for emoji, name, balance in available_balances
        ]
        funds_lines += [
            f"{_ui_emoji(emoji)} {esc(name)}: — <i>{_('bal.postpaid_suffix')}</i>"
            for emoji, name in postpaid_providers
        ]
        sections.append(stack(_("bal.available_funds"), *funds_lines))

    # Section 2: Charges for the current month as compact lines.
    if monthly_expenses:
        expense_lines = [
            f"{_ui_emoji(emoji)} {esc(name)}: ${amount:,.2f}"
            for emoji, name, amount in monthly_expenses
        ]
        sections.append(stack(_("bal.monthly_expenses"), *expense_lines))

    # Section 3: Unavailable providers (stacked lines — italic suffix needs tags,
    # so names are escaped explicitly here rather than via a table cell).
    if unavailable:
        unavailable_lines = [
            f"{_ui_emoji(emoji)} {esc(name)} <i>{_('bal.no_api_suffix')}</i>"
            for emoji, name in unavailable
        ]
        sections.append(stack(_("bal.unavailable"), *unavailable_lines))

    sections.append(_("bal.choose_provider"))
    return blocks(*sections)


def format_balance_history(
    records: list[BalanceRecord],
    period: int,
    provider_emojis: dict,
    provider_filter: str | None = None,
) -> str:
    """
    Format the balance history screen.

    Args:
        records: List of balance records for the period
        period: Period in days
        provider_emojis: Dict of provider emojis {provider_alias: emoji}
        provider_filter: Filter by provider (alias), or None for all

    Returns:
        str: Formatted message in the active language
    """
    if provider_filter:
        title = _(
            "bal.history_title_provider",
            emoji=_ui_emoji(provider_emojis.get(provider_filter, "")),
            provider=esc(provider_filter),
            period=period,
        )
    else:
        title = _("bal.history_title_all", period=period)

    if not records:
        return blocks(title, _("bal.history_insufficient"), _("bal.history_wait"))

    # Newest first, last 10 records, one compact line each.
    sorted_records = sorted(records, key=lambda r: r.timestamp, reverse=True)
    history_lines: list[str] = []
    for record in sorted_records[:10]:
        # Use provider_alias if present, otherwise provider_type for legacy
        record_alias = record.provider_alias or record.provider_type
        emoji = _ui_emoji(provider_emojis.get(record_alias, ""))
        timestamp = record.timestamp.strftime("%Y-%m-%d %H:%M")
        history_lines.append(
            f"{timestamp} · {emoji} {esc(record_alias)}: {esc(record.format_summary())}"
        )

    sections: list[str] = [title, stack(*history_lines)]

    if len(sorted_records) > 10:
        sections.append(plural("bal.history_more", len(sorted_records) - 10))

    if provider_filter:
        sections.append(_("bal.history_only_provider", provider=esc(provider_filter)))
    else:
        sections.append(_("bal.history_all_providers"))

    return blocks(*sections)


# Balance-trend value -> (emoji, catalog key). The dict keys are code-coupled
# (returned by the burn-rate analysis); the words are translated.
_TREND_EMOJI: dict[str, str] = {
    "increasing": "📈",
    "decreasing": "📉",
    "stable": "➡️",
    "unknown": "❓",
}
_TREND_KEYS: dict[str, str] = {
    "increasing": "trend.increasing",
    "decreasing": "trend.decreasing",
    "stable": "trend.stable",
    "unknown": "trend.unknown",
}


def format_balance_provider_detail(
    provider_emoji: str,
    provider_name: str,
    record: BalanceRecord | None,
    burn_rate: float | None,
    days_left: float | None,
    trend: str,
    supports_balance: bool,
) -> str:
    """
    Format the detailed provider balance screen.

    Supports two billing models:
    - Prepaid (Vultr): shows the balance, pending charges, and burn metrics
    - Postpaid (AWS): shows the month's costs, without burn metrics

    Args:
        provider_emoji: Provider emoji
        provider_name: Provider name
        record: Balance record (None if not supported)
        burn_rate: Average spend per day (None if there is not enough data)
        days_left: Forecast of days until depletion
        trend: Balance change trend
        supports_balance: Whether the provider supports the balance API

    Returns:
        str: Formatted message in the active language
    """
    title = f"{_ui_emoji(provider_emoji)} <b>{esc(provider_name)}</b>"

    if not supports_balance or record is None:
        return blocks(
            title,
            _("bal.detail_unavailable"),
            _("bal.detail_no_api_body", provider=esc(provider_name)),
            _("bal.detail_check_manually"),
        )

    last_check = _(
        "bal.detail_last_check", timestamp=record.timestamp.strftime("%Y-%m-%d %H:%M:%S")
    )

    # Postpaid provider (AWS): show the month-to-date costs, no burn metrics.
    if record.billing_model == "postpaid":
        return blocks(
            title,
            stack(
                _("bal.detail_postpaid_costs", value=record.display_value),
                _("bal.detail_postpaid_hint"),
            ),
            last_check,
        )

    # Prepaid provider (Vultr/Hetzner): balance breakdown + burn/forecast/trend.
    sections: list[str] = [title]
    if isinstance(record, PrepaidBalanceRecord):
        sections.append(
            stack(
                _("bal.detail_available_balance", value=record.effective_balance),
                _("bal.detail_account_balance", value=record.balance),
                _("bal.detail_pending", value=record.pending_charges),
            )
        )

        # Burn rate, depletion forecast, and trend.
        analytics: list[str] = []
        if burn_rate is not None and burn_rate > 0:
            analytics.append(_("bal.detail_burn", value=burn_rate))
            analytics.append(_("bal.detail_burn_monthly", value=burn_rate * 30))
        else:
            analytics.append(_("bal.detail_burn_insufficient"))
            analytics.append(_("bal.detail_burn_insufficient_hint"))

        if days_left is not None:
            if days_left > 0:
                days_int = int(days_left)
                analytics.append(plural("bal.forecast_days", days_int))
                period = format_days_as_period(days_int)
                if period:
                    analytics.append(_("bal.detail_forecast_period", period=period))
            else:
                analytics.append(_("bal.detail_forecast_depleted"))
        else:
            analytics.append(_("bal.detail_forecast_none"))

        trend_emoji = _TREND_EMOJI.get(trend, "❓")
        trend_word = _(_TREND_KEYS.get(trend, "trend.unknown"))
        analytics.append(f"{trend_emoji} " + _("bal.detail_trend_label") + f" {trend_word}")
        sections.append(stack(*analytics))

        # Last deposit information (prepaid only).
        if record.last_payment_date and record.last_payment_amount:
            sections.append(
                stack(
                    _("bal.detail_last_deposit"),
                    _(
                        "bal.detail_deposit_date",
                        date=record.last_payment_date.strftime("%Y-%m-%d %H:%M"),
                    ),
                    _("bal.detail_deposit_amount", value=record.last_payment_amount),
                )
            )

    sections.append(last_check)
    return blocks(*sections)
