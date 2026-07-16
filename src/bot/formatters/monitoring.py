"""Formatters for the monitoring router."""

import logging
from datetime import datetime, timezone
from typing import Any
from multiprocessing.managers import DictProxy

from ...models import Server, PingStatistics, PingResult
from ...storage import SqliteStatisticsRepository
from ...storage.balance import BalanceRepository
from ...providers.manager import ProviderManager
from ..i18n import _
from ..utils.rich import blocks, details, stack
from .common import (
    esc,
    format_number,
    plain,
    provider_emoji,
    stats_metric_line,
    strip_rule,
)
from .balance import collect_provider_balances

logger = logging.getLogger(__name__)


def format_monitoring_dashboard(
    servers: list[Server],
    shared_state: DictProxy,
    stats_repo: SqliteStatisticsRepository,
    balance_repo: BalanceRepository | None = None,
    provider_manager: ProviderManager | None = None,
) -> str:
    """
    Format a dashboard with the overall monitoring statistics.

    Args:
        servers: List of servers.
        shared_state: Shared state of the servers.
        stats_repo: Statistics repository.
        balance_repo: Balance repository (optional).
        provider_manager: Provider manager (optional).

    Returns:
        Formatted dashboard text in the active language.
    """
    if not servers:
        return _("mon.empty")

    # Count the server statuses
    total_servers = len(servers)
    online_count = 0
    offline_count = 0
    unknown_count = 0

    # Per-provider statistics
    provider_stats: dict[str, dict[str, int]] = {}

    for server in servers:
        # Read the status from shared_state
        server_key = server.composite_key
        state = shared_state.get(server_key, {})
        status = state.get("status", "unknown")

        if status == "online":
            online_count += 1
        elif status == "offline":
            offline_count += 1
        else:
            unknown_count += 1

        # Count servers per provider_alias (effective_alias accounts for legacy)
        provider_key = server.effective_alias
        if provider_key not in provider_stats:
            provider_stats[provider_key] = {"total": 0, "online": 0, "offline": 0}
        provider_stats[provider_key]["total"] += 1
        if status == "online":
            provider_stats[provider_key]["online"] += 1
        elif status == "offline":
            provider_stats[provider_key]["offline"] += 1

    # Aggregate the overall ping statistics for the last 24 hours
    total_pings = 0
    successful_pings = 0
    failed_pings = 0
    timeout_pings = 0
    uptime_sum = 0.0
    servers_with_stats = 0

    for server in servers:
        stats_24h = stats_repo.get_recent_statistics(server.id, server.effective_alias, hours=24)
        if stats_24h and stats_24h.total_pings > 0:
            total_pings += stats_24h.total_pings
            successful_pings += stats_24h.successful_pings
            failed_pings += stats_24h.failed_pings
            timeout_pings += stats_24h.timeout_pings
            uptime_sum += stats_24h.uptime_percentage
            servers_with_stats += 1

    # Compute the average uptime
    avg_uptime = uptime_sum / servers_with_stats if servers_with_stats > 0 else 0.0

    # Build a compact rich screen: a bold title then blank-line-separated
    # sections of <br>-stacked lines (no cards, no tables) so the whole dashboard
    # fits one phone screen. strip_rule() drops the legacy ━━━ header decoration.
    sections: list[str] = [_("mon.dashboard_title")]

    # Servers: header (with total) + status counts on a single inline line.
    sections.append(
        stack(
            strip_rule(_("mon.section_servers")) + f" — {total_servers}",
            f"🟢 {online_count} · 🔴 {offline_count} · ❓ {unknown_count}",
        )
    )

    # Finances (only when at least one provider reports balance).
    if balance_repo is not None and provider_manager is not None:
        provider_balances = collect_provider_balances(balance_repo, provider_manager)

        # Keep only providers that support balance reporting
        providers_with_balance = [
            (name, data)
            for name, data in provider_balances.items()
            if data["supports_balance"]
        ]

        if providers_with_balance:
            # Sum the total balance (prepaid) and the expenses
            total_balance = 0.0
            total_expenses = 0.0

            for _name, data in providers_with_balance:
                balance = data.get("balance")
                billing_model = data.get("billing_model", "prepaid")

                if billing_model == "prepaid" and balance is not None:
                    total_balance += balance

                # Expenses: pending_charges (prepaid) or monthly_costs (postpaid)
                pending = data.get("pending_charges")
                monthly = data.get("monthly_costs")
                if pending is not None:
                    total_expenses += pending
                if monthly is not None:
                    total_expenses += monthly

            sections.append(
                stack(
                    strip_rule(_("mon.section_finance", count=len(providers_with_balance))),
                    _("mon.finance_balance", amount=total_balance),
                    _("mon.finance_expenses", amount=total_expenses),
                )
            )

    # Per-provider breakdown as compact lines (emoji + alias + online/total).
    if provider_stats:
        provider_lines: list[str] = []
        for alias, stats in sorted(provider_stats.items()):
            line = f"{provider_emoji(alias)} {esc(alias)} · 🟢 {stats['online']}/{stats['total']}"
            if stats["offline"] > 0:
                line += f" · 🔴 {stats['offline']}"
            provider_lines.append(line)
        sections.append(stack(strip_rule(_("mon.section_by_provider")), *provider_lines))

    # Aggregate 24-hour ping statistics on a single compact line.
    if total_pings > 0:
        stats_body = (
            f"✅ {format_number(successful_pings)}"
            f" · ❌ {format_number(failed_pings)} · ⏱ {format_number(timeout_pings)}"
            f" · ⬆ {avg_uptime:.2f}%"
        )
    else:
        stats_body = _("mon.no_ping_data")
    sections.append(stack(strip_rule(_("mon.section_stats_24h")), stats_body))

    return blocks(*sections)


def format_servers_list(servers: list[Server], shared_state: DictProxy, page: int = 0) -> str:
    """
    Format the server list for display.

    Args:
        servers: List of servers.
        shared_state: Shared state of the servers.
        page: Page number.

    Returns:
        Formatted text with the server list in the active language.
    """
    if not servers:
        return _("mon.empty")

    # Count the statuses
    online_count = 0
    offline_count = 0
    unknown_count = 0

    for server in servers:
        server_key = server.composite_key
        state = shared_state.get(server_key, {})
        status = state.get("status", "unknown")

        if status == "online":
            online_count += 1
        elif status == "offline":
            offline_count += 1
        else:
            unknown_count += 1

    return blocks(
        _("mon.list_title"),
        stack(
            _("mon.total_servers", count=len(servers)),
            _(
                "mon.status_inline",
                online=online_count,
                offline=offline_count,
                unknown=unknown_count,
            ),
        ),
        _("mon.choose_server"),
    )


def _stats_period_line(period_label: str, stats: PingStatistics | None) -> str:
    """Return one compact statistics line for a period.

    Args:
        period_label: Short period label (e.g. "1h").
        stats: The period's statistics, or None / empty when no data exists.

    Returns:
        str: ``label · ⬆..·✓..·⚡..`` (or ``label · —`` when the period has no pings).
    """
    if stats is None or stats.total_pings == 0:
        return f"{period_label} · —"
    return f"{period_label} · {stats_metric_line(stats)}"


def format_server_details(
    server: Server,
    state: dict[str, Any],
    stats_24h: PingStatistics | None,
    recent_errors: list[PingResult],
) -> str:
    """
    Format detailed information about a server as a rich message.

    Renders a visible key:value block, a compact 24-hour statistics table, and a
    collapsible <details> list of recent problems.

    Args:
        server: Server.
        state: Current state from shared_state.
        stats_24h: Statistics for the last 24 hours.
        recent_errors: Recent errors (failed/timeout pings).

    Returns:
        Formatted rich-HTML text with the server details in the active language.
    """
    # Resolve the status
    status = state.get("status", "unknown")
    if status == "online":
        status_emoji = "✅"
        status_text = _("status.online")
    elif status == "offline":
        status_emoji = "❌"
        status_text = _("status.offline")
    else:
        status_emoji = "❓"
        status_text = _("status.unknown")

    # Visible key:value detail lines (IP in <code> for monospace + easy copy).
    info_lines = [
        _("details.status_label") + f" {status_emoji} {status_text}",
        _("details.provider_label") + f" {esc(server.effective_alias.upper())}",
        _("details.ip_label") + f" <code>{esc(server.ip)}</code>",
    ]
    if server.region:
        info_lines.append(_("details.region_label") + f" {esc(server.region)}")
    if server.plan:
        info_lines.append(_("details.plan_label") + f" {esc(server.plan)}")
    if server.os:
        info_lines.append(_("details.os_label") + f" {esc(server.os)}")
    if server.vcpu_count and server.ram_mb:
        resources = f" {server.vcpu_count} vCPU | {server.ram_mb} MB RAM"
        if server.disk_gb:
            resources += f" | {server.disk_gb} " + _("details.disk_suffix")
        info_lines.append(_("details.resources_label") + resources)

    last_check = state.get("last_ping_time")
    if last_check:
        info_lines.append(_("details.last_ping_label") + f" {esc(last_check)}")
    response_time = state.get("response_time_ms")
    if response_time is not None:
        info_lines.append(_("details.response_time_label") + f" {response_time:.2f} ms")
    monitoring_state = _("details.monitoring_on") if server.enabled else _("details.monitoring_off")
    info_lines.append(_("details.monitoring_label") + f" {monitoring_state}")

    sections: list[str] = [
        f"🖥️ <b>{esc(server.get_display_name())}</b>",
        stack(*info_lines),
    ]

    # 24-hour statistics on one compact line (only with real data:
    # get_recent_statistics() returns a non-None record with total_pings=0 for a
    # no-data window, matching the total_pings>0 guard used at every other site).
    if stats_24h and stats_24h.total_pings > 0:
        sections.append(
            stack(
                strip_rule(_("details.stats_24h_header")),
                stats_metric_line(stats_24h),
            )
        )

    # Recent problems in a collapsible <details> block (secondary information).
    if recent_errors:
        problem_entries: list[str] = []
        for error in recent_errors[:5]:
            # Format the elapsed time
            try:
                time_diff = datetime.now(timezone.utc) - error.timestamp
                if time_diff.total_seconds() < 60:
                    time_ago = _("time.just_now")
                elif time_diff.total_seconds() < 3600:
                    minutes = int(time_diff.total_seconds() / 60)
                    time_ago = _("time.min_ago", n=minutes)
                elif time_diff.total_seconds() < 86400:
                    hours = int(time_diff.total_seconds() / 3600)
                    time_ago = _("time.hours_ago", n=hours)
                else:
                    days = int(time_diff.total_seconds() / 86400)
                    time_ago = _("time.days_ago", n=days)
            except Exception as e:
                logger.warning(f"Failed to calculate time diff for error: {e}")
                time_ago = _("time.na")

            # Technical enum value — not translated.
            entry = f"🔴 {esc(error.status.value.upper())} ({time_ago})"
            if error.error:
                entry = stack(entry, f"<i>{esc(error.error)}</i>")
            problem_entries.append(entry)
        sections.append(details(plain(_("details.recent_problems")), stack(*problem_entries)))

    return blocks(*sections)


def format_statistics(
    server: Server,
    stats_1h: PingStatistics | None,
    stats_24h: PingStatistics | None,
    stats_7d: PingStatistics | None,
) -> str:
    """
    Format the full statistics across different periods.

    Args:
        server: Server.
        stats_1h: Statistics for the last 1 hour.
        stats_24h: Statistics for the last 24 hours.
        stats_7d: Statistics for the last 7 days.

    Returns:
        Formatted rich-HTML text with the statistics in the active language.
    """
    # One compact line per period (1h / 24h / 7d); empty periods render as "—".
    return blocks(
        _("stats.title", name=esc(server.get_display_name())),
        stack(
            _stats_period_line("1h", stats_1h),
            _stats_period_line("24h", stats_24h),
            _stats_period_line("7d", stats_7d),
        ),
    )
