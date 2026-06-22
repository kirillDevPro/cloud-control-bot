"""Functions for sending administrator notifications and reporting delivery status.

Every notification is BROADCAST to all administrators, who may each have a
different UI language. Delivery therefore renders the message PER RECIPIENT in
that admin's stored language: each ``send_*`` builds a ``render(language) -> str``
callback, and :func:`_broadcast_to_admins` resolves every admin's language and
renders the message for them individually.

Background tasks that raise generic critical alerts pass i18n keys (not
pre-rendered text) via :func:`render_message` / :func:`render_plural`, so those
alerts are localized per recipient too.
"""

import asyncio
import logging
from collections.abc import Callable

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramNetworkError, TelegramRetryAfter

from .formatters.common import esc
from .i18n import get_user_language, translate, translate_error, translate_plural

logger = logging.getLogger(__name__)

# A per-recipient renderer: given a language code, returns the message for it.
Renderer = Callable[[str], str]


def _escape_str_kwargs(kwargs: dict[str, object]) -> dict[str, object]:
    """HTML-escape string values in a kwargs mapping, passing non-strings through.

    Messages are sent with parse_mode=HTML, so any externally-sourced string
    (server name, provider label, error text) must be escaped before it is
    interpolated into a template. Numbers and other non-strings are left as-is so
    their format specs (e.g. ``{ratio:.0f}``) still apply.

    Args:
        kwargs: Substitution values for a translation template.

    Returns:
        dict[str, object]: The same mapping with string values HTML-escaped.
    """
    return {key: (esc(value) if isinstance(value, str) else value) for key, value in kwargs.items()}


def render_message(key: str, **kwargs: object) -> Renderer:
    """Build a per-recipient renderer for a plain catalog key.

    String kwargs are HTML-escaped once up front (language-independent), so the
    returned closure only needs to resolve the template per language. Intended for
    background-task alert bodies that pass i18n keys instead of pre-rendered text.

    Args:
        key: Catalog message key.
        **kwargs: Substitution values (string values are HTML-escaped).

    Returns:
        Renderer: ``language -> localized, formatted string``.
    """
    safe = _escape_str_kwargs(kwargs)
    return lambda language: translate(key, language, **safe)


def render_error_message(key: str, error: BaseException) -> Renderer:
    """Build a per-recipient renderer that embeds a localized exception detail.

    The exception is localized in EACH recipient's own language (so a provider
    failure reads in their UI language, not the language the code raised it in)
    and HTML-escaped before being interpolated into the wrapper template ``key``
    as ``{error}``. Use this instead of ``render_message(key, error=str(exc))``,
    which would freeze the detail in one language for every recipient.

    Args:
        key: Catalog key whose template contains an ``{error}`` placeholder.
        error: The exception whose detail to localize and embed.

    Returns:
        Renderer: ``language -> wrapper template with the per-language error``.
    """
    return lambda language: translate(key, language, error=esc(translate_error(error, language)))


def render_plural(key: str, n: int, **kwargs: object) -> Renderer:
    """Build a per-recipient renderer for a plural-aware catalog key.

    Args:
        key: Catalog plural key.
        n: The count selecting the plural form (also exposed as ``{n}``).
        **kwargs: Extra substitution values (string values are HTML-escaped).

    Returns:
        Renderer: ``language -> localized, formatted plural string``.
    """
    safe = _escape_str_kwargs(kwargs)
    return lambda language: translate_plural(key, n, language, **safe)


def _render_duration(seconds: int) -> Renderer:
    """Build a per-recipient renderer for an outage duration ("~X h" / "~Y min").

    The duration must be localized PER RECIPIENT (an English admin should not see
    Russian unit abbreviations), so it is rendered inside the broadcast loop rather
    than pre-formatted. Mirrors the original hour/minute thresholds.

    Args:
        seconds: Outage duration in seconds.

    Returns:
        Renderer: ``language -> localized duration string``.
    """
    hours = seconds / 3600
    if hours >= 1:
        return lambda language: translate("outage.duration_hours", language, hours=hours)
    minutes = max(1, seconds // 60)
    return lambda language: translate("outage.duration_minutes", language, minutes=minutes)


async def _broadcast_to_admins(
    bot: Bot, admin_ids: list[int], render: Renderer, *, log_label: str
) -> bool:
    """
    Broadcast a per-recipient-rendered message to all administrators.

    The message is rendered for each admin in that admin's stored language. Each
    send is attempted independently. Telegram flood-control errors are retried
    once after the requested delay; all Telegram and unexpected client/session
    errors are logged and swallowed so notification failures do not crash
    background processors.

    Args:
        bot: Bot instance
        admin_ids: List of administrator IDs
        render: Callback that renders the message for a given language code
        log_label: Lowercase notification label used in logs
            (for example, "server down notification")

    Returns:
        bool: True if the message was delivered to at least one administrator,
            False if every send failed. ping_results_processor gates its anti-flap
            cooldown and last-notified state on this, so an undelivered down/up alert
            is retried on the next result instead of being silently consumed.
    """
    label_capitalized = log_label[:1].upper() + log_label[1:]
    delivered = False
    for admin_id in admin_ids:
        # Render in the recipient's own language.
        message = render(get_user_language(admin_id))
        try:
            await bot.send_message(admin_id, message)
            logger.info(f"{label_capitalized} sent to admin {admin_id}")
            delivered = True
        except TelegramRetryAfter as e:
            # Flood control fires exactly when many alerts go out at once (e.g. a
            # provider outage downing several servers); wait out the window and
            # retry ONCE so a critical alert is not silently dropped.
            logger.warning(f"Rate limited for {admin_id}, retry after {e.retry_after}s")
            try:
                await asyncio.sleep(e.retry_after)
                await bot.send_message(admin_id, message)
                logger.info(f"{label_capitalized} sent to admin {admin_id} after retry")
                delivered = True
            except Exception as retry_error:
                logger.error(
                    f"Failed to resend {log_label} to {admin_id} after rate limit: {retry_error}",
                    exc_info=True,
                )
        except TelegramNetworkError as e:
            logger.error(f"Network error sending {log_label} to {admin_id}: {e}", exc_info=True)
        except TelegramAPIError as e:
            logger.error(
                f"Telegram API error sending {log_label} to {admin_id}: {e}", exc_info=True
            )
        except Exception as e:
            # Terminal catch-all: a NON-Telegram exception (ClientDecodeError on a
            # malformed/HTML gateway response — it subclasses AiogramError, not
            # TelegramAPIError — or a bare asyncio.TimeoutError / RuntimeError from the
            # aiohttp session layer) must never propagate to a caller. ping_results_processor
            # calls these sends inline, so an un-caught error here would otherwise kill it.
            logger.error(
                f"Unexpected error sending {log_label} to {admin_id}: {e}", exc_info=True
            )

    return delivered


async def send_server_down_notification(
    bot: Bot, admin_ids: list[int], server_name: str, server_ip: str, error: str | None
) -> bool:
    """
    Send a notification that a server has gone down.

    Args:
        bot: Bot instance
        admin_ids: List of administrator IDs
        server_name: Server name
        server_ip: Server IP address
        error: Error description, if any

    Returns:
        bool: True if delivered to at least one administrator (see _broadcast_to_admins).
    """
    name, ip = esc(server_name), esc(server_ip)
    error_safe = esc(error) if error else None

    def render(language: str) -> str:
        """Render the server-down message in one recipient language.

        Args:
            language: Target language code for the recipient.

        Returns:
            str: Localized server-down notification body.
        """
        message = (
            translate("notif.server_down.title", language)
            + "\n\n"
            + translate("notif.server_down.body", language, name=name, ip=ip)
        )
        if error_safe is not None:
            message += "\n\n" + translate("notif.error_label", language, error=error_safe)
        return message

    return await _broadcast_to_admins(
        bot, admin_ids, render, log_label="server down notification"
    )


async def send_server_up_notification(
    bot: Bot,
    admin_ids: list[int],
    server_name: str,
    server_ip: str,
    response_time_ms: float | None,
) -> bool:
    """
    Send a notification that a server has recovered.

    Args:
        bot: Bot instance
        admin_ids: List of administrator IDs
        server_name: Server name
        server_ip: Server IP address
        response_time_ms: Response time in milliseconds

    Returns:
        bool: True if delivered to at least one administrator (see _broadcast_to_admins).
    """
    name, ip = esc(server_name), esc(server_ip)

    def render(language: str) -> str:
        """Render the server-up message in one recipient language.

        Args:
            language: Target language code for the recipient.

        Returns:
            str: Localized server-up notification body.
        """
        message = (
            translate("notif.server_up.title", language)
            + "\n\n"
            + translate("notif.server_up.body", language, name=name, ip=ip)
        )
        if response_time_ms is not None:
            message += "\n\n" + translate(
                "notif.response_time_label", language, ms=f"{response_time_ms:.2f}"
            )
        return message

    return await _broadcast_to_admins(bot, admin_ids, render, log_label="server up notification")


async def send_low_balance_notification(
    bot: Bot,
    admin_ids: list[int],
    balance: float,
    threshold: float,
    days_left: float | None,
    provider_name: str = "Unknown",
) -> None:
    """
    Send a low balance notification.

    Delivery failures are logged by _broadcast_to_admins() and not returned to the caller.

    Args:
        bot: Bot instance
        admin_ids: List of administrator IDs
        balance: Current balance in USD
        threshold: Threshold value in USD
        days_left: Forecast of days until depletion, if available
        provider_name: Provider name (VULTR, HETZNER, etc.)

    Returns:
        None.
    """
    provider = esc(provider_name)

    def render(language: str) -> str:
        """Render the low-balance message in one recipient language.

        Args:
            language: Target language code for the recipient.

        Returns:
            str: Localized low-balance notification body.
        """
        message = (
            translate("notif.low_balance.title", language, provider=provider)
            + "\n\n"
            + translate("notif.low_balance.body", language, balance=balance, threshold=threshold)
            + "\n\n"
        )
        if days_left is not None and days_left > 0:
            message += (
                translate_plural("notif.low_balance.forecast", int(days_left), language) + "\n\n"
            )
        elif days_left is not None and days_left <= 0:
            # <= 0 (not == 0) so a tiny negative float from the burn-rate division
            # on a fully-depleted balance still shows the "depleted" line.
            message += translate("notif.low_balance.depleted", language) + "\n\n"
        message += translate("notif.low_balance.top_up", language, provider=provider)
        return message

    await _broadcast_to_admins(
        bot, admin_ids, render, log_label=f"low balance notification for {provider_name}"
    )


async def send_critical_error_notification(
    bot: Bot,
    admin_ids: list[int],
    *,
    title_key: str,
    body: Renderer,
    title_kwargs: dict[str, object] | None = None,
) -> bool:
    """
    Send a critical error notification to administrators, localized per recipient.

    Used to alert about critical problems that require immediate attention (an
    invalid API token, a dead subsystem, a stalled background task). The body is
    a per-recipient renderer (built with :func:`render_message` /
    :func:`render_plural`, or a custom closure) so callers pass i18n keys, not
    pre-rendered text.

    Args:
        bot: Bot instance
        admin_ids: List of administrator IDs
        title_key: Catalog key for the short alert category shown in the header
            (interpolated into "Critical error: {error_type}").
        body: Renderer producing the alert body for a given language.
        title_kwargs: Optional substitutions for the title key (string values are
            HTML-escaped).

    Returns:
        bool: True if delivered to at least one administrator (see _broadcast_to_admins).
            Callers that retry until delivered (e.g. the stall watchdog) gate on this.
    """
    safe_title_kwargs = _escape_str_kwargs(title_kwargs or {})

    def render(language: str) -> str:
        """Render the critical-error message in one recipient language.

        Args:
            language: Target language code for the recipient.

        Returns:
            str: Localized critical-error notification body.
        """
        error_type = translate(title_key, language, **safe_title_kwargs)
        return (
            translate("notif.critical.title", language, error_type=error_type)
            + "\n\n"
            + body(language)
            + "\n\n"
            + translate("notif.critical.check_logs", language)
        )

    return await _broadcast_to_admins(
        bot, admin_ids, render, log_label="critical error notification"
    )


async def send_provider_outage_notification(
    bot: Bot,
    admin_ids: list[int],
    provider_label: str,
    duration_seconds: int,
    failures: int,
    last_error: BaseException,
) -> None:
    """
    Send a notification about a SUSTAINED transient provider outage.

    Unlike a critical error, this is used only when a transient failure
    (5xx, rate limit, network) lasts for several consecutive sync cycles and is
    clearly not an instantaneous API "blip". Sent once per outage period;
    recovery is reported via send_provider_recovered_notification.
    Delivery failures are logged by _broadcast_to_admins() and not returned.

    Args:
        bot: Bot instance
        admin_ids: List of administrator IDs
        provider_label: Human-readable provider name (display_name)
        duration_seconds: Outage duration in seconds (localized per recipient)
        failures: Number of consecutive failed checks
        last_error: The last error exception; localized per recipient (its full
            technical text is logged separately, not shown here)

    Returns:
        None.
    """
    provider = esc(provider_label)
    duration_render = _render_duration(duration_seconds)

    def render(language: str) -> str:
        """Render the provider-outage message in one recipient language.

        Args:
            language: Target language code for the recipient.

        Returns:
            str: Localized provider-outage notification body.
        """
        checks = translate_plural("plural.checks_in_row", failures, language)
        return (
            translate("notif.provider_outage.title", language, provider=provider)
            + "\n\n"
            + translate(
                "notif.provider_outage.body",
                language,
                duration=duration_render(language),
                checks=checks,
            )
            + "\n\n"
            + translate(
                "notif.provider_outage.last_error",
                language,
                error=esc(translate_error(last_error, language)),
            )
            + "\n\n"
            + translate("notif.provider_outage.footer", language)
        )

    await _broadcast_to_admins(
        bot, admin_ids, render, log_label=f"provider outage notification for {provider_label}"
    )


async def send_provider_recovered_notification(
    bot: Bot,
    admin_ids: list[int],
    provider_label: str,
    duration_seconds: int,
) -> None:
    """
    Send a notification that a provider's availability has recovered.

    Sent only if an alert was previously sent for this provider
    (a sustained outage or a critical error) — to close the "open" incident.

    Delivery failures are logged by _broadcast_to_admins() and not returned.

    Args:
        bot: Bot instance
        admin_ids: List of administrator IDs
        provider_label: Human-readable provider name (display_name)
        duration_seconds: Outage duration in seconds (localized per recipient)

    Returns:
        None.
    """
    provider = esc(provider_label)
    duration_render = _render_duration(duration_seconds)

    def render(language: str) -> str:
        """Render the provider-recovered message in one recipient language.

        Args:
            language: Target language code for the recipient.

        Returns:
            str: Localized provider-recovered notification body.
        """
        return (
            translate("notif.provider_recovered.title", language, provider=provider)
            + "\n\n"
            + translate(
                "notif.provider_recovered.body", language, duration=duration_render(language)
            )
        )

    await _broadcast_to_admins(
        bot, admin_ids, render, log_label=f"provider recovered notification for {provider_label}"
    )


async def send_server_added_notification(
    bot: Bot,
    admin_ids: list[int],
    server_name: str,
    server_ip: str,
    provider_name: str,
    region: str | None = None,
) -> None:
    """
    Send a notification that a new server has been added.

    Delivery failures are logged by _broadcast_to_admins() and not returned.

    Args:
        bot: Bot instance
        admin_ids: List of administrator IDs
        server_name: Server name
        server_ip: Server IP address
        provider_name: Provider name (vultr, hetzner, etc.)
        region: Server region (optional)

    Returns:
        None.
    """
    name, ip, provider = esc(server_name), esc(server_ip), esc(provider_name.upper())
    region_safe = esc(region) if region else None

    def render(language: str) -> str:
        """Render the server-added message in one recipient language.

        Args:
            language: Target language code for the recipient.

        Returns:
            str: Localized server-added notification body.
        """
        message = (
            translate("notif.server_added.title", language)
            + "\n\n"
            + translate("notif.server_added.body", language, name=name, ip=ip, provider=provider)
        )
        if region_safe is not None:
            message += "\n\n" + translate("notif.server_added.region", language, region=region_safe)
        message += "\n\n" + translate("notif.server_added.monitoring_started", language)
        return message

    await _broadcast_to_admins(bot, admin_ids, render, log_label="server added notification")


async def send_server_removed_notification(
    bot: Bot, admin_ids: list[int], server_name: str, server_ip: str, provider_name: str
) -> None:
    """
    Send a notification that a server has been removed.

    Delivery failures are logged by _broadcast_to_admins() and not returned.

    Args:
        bot: Bot instance
        admin_ids: List of administrator IDs
        server_name: Server name
        server_ip: Server IP address
        provider_name: Provider name (vultr, hetzner, etc.)

    Returns:
        None.
    """
    name, ip, provider = esc(server_name), esc(server_ip), esc(provider_name.upper())

    def render(language: str) -> str:
        """Render the server-removed message in one recipient language.

        Args:
            language: Target language code for the recipient.

        Returns:
            str: Localized server-removed notification body.
        """
        return (
            translate("notif.server_removed.title", language)
            + "\n\n"
            + translate("notif.server_removed.body", language, name=name, ip=ip, provider=provider)
        )

    await _broadcast_to_admins(bot, admin_ids, render, log_label="server removed notification")
