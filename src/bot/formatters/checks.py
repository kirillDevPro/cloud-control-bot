"""Formatters for the service-checks screens (compact rich messages).

Screens stay compact: <br>-stacked emoji lines, no tables/blockquotes, sized to one phone
screen. Every externally-sourced leaf (URL, host, error) is escaped.
"""

from __future__ import annotations

from typing import Any

from ...models import Server
from ...models.service_check import CHECK_TYPE_EMOJI, CheckDefinition, CheckType
from ..i18n import _
from ..utils.rich import blocks, stack
from .common import esc


def _check_target(check: CheckDefinition) -> str:
    """Return the human target of a check (URL for HTTP, host:port label otherwise).

    Args:
        check: The check definition.

    Returns:
        str: An UNescaped target string (callers escape before interpolation).
    """
    if check.type == CheckType.HTTP:
        return check.url or "?"
    return f":{check.effective_port}"


def format_checks_list(server: Server, checks: list[CheckDefinition]) -> str:
    """Format the service-checks list screen for a server.

    The individual checks are the buttons; this body is just the header and a prompt, so
    it always fits one screen regardless of how many checks exist.

    Args:
        server: The server whose checks are shown.
        checks: The server's configured checks.

    Returns:
        str: The rich HTML body.
    """
    title = _("checks.list.title", server=esc(server.get_display_name()))
    if not checks:
        return blocks(title, _("checks.list.empty"))
    return blocks(title, _("checks.list.prompt"))


def format_check_detail(
    server: Server,
    check: CheckDefinition,
    stats: dict[str, Any] | None,
    ssl_state: dict[str, Any] | None,
) -> str:
    """Format the detail screen for a single check.

    Args:
        server: The server the check belongs to.
        check: The check being shown.
        stats: This check's aggregated stats (get_check_statistics entry), or None.
        ssl_state: This check's SSL state (get_ssl_state), or None (non-SSL or never run).

    Returns:
        str: The rich HTML body.
    """
    emoji = CHECK_TYPE_EMOJI.get(check.type, "•")
    # <code>-wrap the technical target (URL / :port) — the codebase convention for IPs/URLs,
    # and it keeps a long URL copyable in the proportional font.
    desc = f"{emoji} {check.type.value.upper()} <code>{esc(_check_target(check))}</code>"
    title = _("checks.detail.title", desc=desc)

    lines: list[str] = []
    lines.append(
        _("checks.detail.enabled") if check.enabled else _("checks.detail.disabled")
    )

    # Aggregated 24h stats (shared across all check types).
    if stats and stats.get("total_checks"):
        pct = f"{stats['uptime_percentage']:.1f}"
        lines.append(
            _(
                "checks.detail.stats",
                pct=pct,
                ok=stats["successful_checks"],
                total=stats["total_checks"],
            )
        )
        avg = stats.get("avg_latency_ms") or 0.0
        if avg > 0:
            lines.append(_("checks.detail.latency", ms=f"{avg:.0f}"))
    else:
        lines.append(_("checks.detail.no_data"))

    # SSL-specific current certificate state.
    if check.type == CheckType.SSL and ssl_state is not None:
        days = ssl_state.get("days_left")
        if days is not None:
            lines.append(_("checks.detail.ssl_days", days=days))
        not_after = ssl_state.get("not_after")
        if not_after is not None:
            lines.append(_("checks.detail.ssl_until", date=not_after.strftime("%Y-%m-%d")))
        verify_error = ssl_state.get("verify_error")
        if verify_error:
            lines.append(_("checks.detail.ssl_problem", detail=esc(verify_error)))

    return blocks(title, stack(*lines))
