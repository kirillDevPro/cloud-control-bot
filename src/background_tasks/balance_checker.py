"""Background task for checking account balances at cloud providers."""

import asyncio
import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from aiogram import Bot

if TYPE_CHECKING:
    from ..storage import BalanceRepository, BaseBalanceRecord
    from ..providers.base import BaseProvider
    from ..providers.manager import ProviderManager

from ..bot.notifications import send_low_balance_notification
from ..storage.balance import PrepaidBalanceRecord

logger = logging.getLogger(__name__)

# Anti-flap: while a balance stays below the threshold, send at most one alert per
# this many seconds (24h). Without this the alert re-fires every check cycle (every
# few hours), which reads as constant nagging.
LOW_BALANCE_ALERT_COOLDOWN_SECONDS = 24 * 60 * 60

# Per-provider wall-clock time (time.time()) of the last DELIVERED low-balance alert,
# keyed by provider alias. Advanced only on confirmed delivery; cleared when the
# balance recovers above the threshold so the next genuine drop alerts immediately.
# In-memory only (resets on restart) and pruned when a provider disappears.
_last_low_balance_alert_at: dict[str, float] = {}


def reset_low_balance_cooldown() -> None:
    """Re-arm all low-balance alerts so the next sub-threshold check alerts immediately.

    Called by the Settings handlers when an admin (re-)enables alerts or changes the
    threshold, so a still-low balance is warned about promptly instead of waiting out
    the leftover cooldown from a previous alert. Being event-driven, it catches an
    OFF -> ON toggle that happens between balance-check cycles — which a once-per-cycle
    sampled transition check would miss.

    Returns:
        None.
    """
    _last_low_balance_alert_at.clear()


async def _maybe_alert_low_balance(
    *,
    bot: Bot,
    balance_repo: "BalanceRepository",  # type: ignore  # noqa: F821
    admin_ids: list[int],
    alias: str,
    provider: "BaseProvider",  # type: ignore  # noqa: F821
    balance_record: "BaseBalanceRecord",  # type: ignore  # noqa: F821
    current_value: float,
    threshold: float,
) -> None:
    """Send a low-balance alert for one provider, respecting the 24h anti-flap cooldown.

    Skips silently while inside the cooldown window. When it sends, the per-provider
    cooldown clock is advanced only on CONFIRMED delivery, so an undelivered alert is
    retried on the next cycle instead of being silently consumed.

    Args:
        bot: aiogram Bot used to send the alert.
        balance_repo: Balance history repository (for the days-until-empty forecast).
        admin_ids: Administrator IDs to notify.
        alias: Provider alias, the cooldown dict key.
        provider: The provider whose balance is low (for its display name).
        balance_record: The fetched balance record (prepaid records log extra detail).
        current_value: The effective balance compared against the threshold, in USD.
        threshold: The active threshold in USD.

    Returns:
        None.
    """
    now = time.time()
    last = _last_low_balance_alert_at.get(alias, 0.0)
    if now - last < LOW_BALANCE_ALERT_COOLDOWN_SECONDS:
        # Still within the cooldown window since the last delivered alert; stay quiet.
        return

    # Detailed logging only for prepaid records (they carry balance/pending fields).
    if isinstance(balance_record, PrepaidBalanceRecord):
        logger.warning(
            f"Low balance detected for {alias}: "
            f"${current_value:.2f} < ${threshold:.2f} "
            f"(balance=${balance_record.balance:.2f}, "
            f"pending=${balance_record.pending_charges:.2f})"
        )
    else:
        logger.warning(
            f"Low balance detected for {alias}: ${current_value:.2f} < ${threshold:.2f}"
        )

    days_left = await asyncio.to_thread(
        balance_repo.estimate_days_until_empty,
        provider_alias=alias,
    )
    delivered = await send_low_balance_notification(
        bot=bot,
        admin_ids=admin_ids,
        balance=current_value,
        threshold=threshold,
        days_left=days_left,
        provider_name=provider.get_provider_display_name(),
    )
    # Advance the cooldown clock only on confirmed delivery; an undelivered alert is
    # retried next cycle.
    if delivered:
        _last_low_balance_alert_at[alias] = now


async def balance_checker(
    bot: Bot,
    balance_repo: "BalanceRepository",  # type: ignore  # noqa: F821
    provider_manager: "ProviderManager",  # type: ignore  # noqa: F821
    admin_ids: list[int],
    check_interval: int,
    threshold_getter: Callable[[], float],
    alerts_enabled_getter: Callable[[], bool] = lambda: True,
    heartbeat: Callable[[], None] = lambda: None,
) -> None:
    """
    Background task that periodically checks account balances.

    The function runs in an infinite loop and:
    1. Fetches the current balance from every provider that supports get_balance()
    2. Saves a record to history (if should_save_balance_history() == True)
    3. Sends a low-balance alert when enabled and the balance is below the threshold
       (only for providers where should_check_balance_threshold() == True)

    The threshold and on/off switch are read through getters on every cycle, so a
    change the admin makes from the Settings menu takes effect without a restart.

    Alerts are anti-flapped: while a balance stays below the threshold the alert is
    sent at most once per LOW_BALANCE_ALERT_COOLDOWN_SECONDS, the cooldown clock is
    advanced only on confirmed delivery, and it is reset when the balance recovers
    above the threshold so a fresh drop alerts immediately.

    Polymorphism:
    - should_save_balance_history() decides whether history should be saved
    - should_check_balance_threshold() decides whether the threshold should be checked
    - display_value - unified value used both for display and for the threshold check

    Args:
        bot: aiogram Bot instance used to send messages
        balance_repo: Balance history repository
        provider_manager: Manager of all cloud providers
        admin_ids: List of administrator IDs to notify
        check_interval: Check interval in seconds
        threshold_getter: Returns the current notification threshold in USD (applied
            only to prepaid providers); read once per cycle so in-bot changes apply live.
        alerts_enabled_getter: Returns whether low-balance alerts are enabled; when it
            returns False the threshold check and notification are skipped (history is
            still saved). Defaults to always-enabled for standalone use/tests.
        heartbeat: Called once per loop iteration so the supervisor can detect a stall.
            Defaults to a no-op for standalone use/tests.

    Returns:
        None. Runs until cancelled.

    Raises:
        asyncio.CancelledError: Re-raised when the task is cancelled.
        Exception: Re-raised on an unrecoverable error outside a check cycle.
    """
    try:
        while True:
            heartbeat()  # progress beat at the top of every loop iteration
            # Sleep before each recurring pass; main.py already performs the startup check.
            await asyncio.sleep(check_interval)

            try:
                # Snapshot the runtime-configurable alert settings once per cycle so a
                # mid-cycle change applies uniformly across this pass. The OFF -> ON
                # re-arm is event-driven (reset_low_balance_cooldown(), called by the
                # Settings handlers on enable), so it is not sampled here.
                alerts_enabled = alerts_enabled_getter()
                threshold = threshold_getter()

                # Snapshot the provider set once so the check loop and the cooldown-prune
                # below operate on the same view (no second get_all_providers() call).
                # Returns dict[str, tuple[BaseProvider, ProviderConfig]].
                providers = provider_manager.get_all_providers()

                # Check the balance at every provider
                for alias, (provider, config) in providers.items():
                    # Skip providers without a balance API (e.g. Hetzner)
                    if not provider.supports_balance():
                        continue

                    try:
                        # Fetch the balance data
                        balance_record = await provider.get_balance()

                        if balance_record is None:
                            continue

                        # Set provider_alias on the record (if not already set)
                        if not balance_record.provider_alias:
                            balance_record.provider_alias = alias

                        # Save to history (polymorphic call)
                        # Offload blocking JSON I/O so it doesn't stall the event loop.
                        # History is saved regardless of the alert on/off switch.
                        if provider.should_save_balance_history():
                            await asyncio.to_thread(balance_repo.add_record, balance_record)

                        # Low-balance threshold handling (prepaid only). The threshold
                        # comparison and the recovery re-arm run regardless of the on/off
                        # switch — only the notification itself is gated by it, so the
                        # cooldown state never goes stale while alerts are off.
                        if provider.should_check_balance_threshold():
                            # display_value returns effective_balance for prepaid
                            current_value = balance_record.display_value
                            if current_value < threshold:
                                if alerts_enabled:
                                    await _maybe_alert_low_balance(
                                        bot=bot,
                                        balance_repo=balance_repo,
                                        admin_ids=admin_ids,
                                        alias=alias,
                                        provider=provider,
                                        balance_record=balance_record,
                                        current_value=current_value,
                                        threshold=threshold,
                                    )
                            else:
                                # Balance recovered above the threshold: re-arm so the
                                # next genuine drop alerts immediately, not after the
                                # cooldown window.
                                _last_low_balance_alert_at.pop(alias, None)

                    except Exception as e:
                        logger.error(
                            f"Error checking balance for {alias}: {e}",
                            exc_info=True,
                        )

                # Drop cooldown state for providers that no longer exist (fleet churn),
                # so the in-memory dict cannot leak across provider removals.
                current_aliases = set(providers.keys())
                for stale_alias in [a for a in _last_low_balance_alert_at if a not in current_aliases]:
                    del _last_low_balance_alert_at[stale_alias]

                # Clean up old data (older than 90 days)
                deleted_count = await asyncio.to_thread(balance_repo.cleanup_old_data, days=90)
                if deleted_count > 0:
                    logger.info(f"Cleaned up {deleted_count} old balance records")

            except Exception as e:
                logger.error(f"Error in balance checker cycle: {e}", exc_info=True)

    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error(f"Critical error in balance checker: {e}", exc_info=True)
        raise
