"""Background task that automatically synchronizes servers with provider APIs."""

import asyncio
import logging
import math
from collections.abc import Callable
from dataclasses import dataclass, field
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
    send_suspicious_api_response_notification,
    send_mass_removal_deferred_notification,
)

logger = logging.getLogger(__name__)

# How many CONSECUTIVE failed provider checks must accumulate before a
# transient failure (5xx/timeout/rate-limit) is considered a sustained outage
# and the administrator is notified. Persistent errors (auth/permissions) alert
# immediately.
OUTAGE_ALERT_THRESHOLD = 3

# Smallest batch of disappearing servers that the ratio guard applies to. Below it a
# removal is always immediate: on a two-server account a single legitimate deletion is
# 50% of the fleet, and making the user wait a full cycle for it buys nothing.
MIN_DEFERRABLE_REMOVALS = 3

# How many consecutive cycles an alias may stay in "deferred removal" before the log says
# so. A set that keeps changing never confirms, which would silently stall removals.
DEFERRAL_WARN_CYCLES = 3

# How long an empty-but-successful response must persist before "this account really is
# empty" beats "the provider API is glitching" as the explanation. Until then the removal
# is skipped entirely. Expressed as a DURATION, not a cycle count, so it keeps its meaning
# when SERVERS_SYNC_INTERVAL changes: the outage that cost a fleet's history produced a
# single empty cycle, while a genuine delete-all still reconciles itself within the hour.
EMPTY_RESPONSE_CONFIRM_SECONDS = 3600


def _empty_confirm_cycles(sync_interval: int) -> int:
    """Return how many consecutive empty responses confirm a genuinely empty account.

    Args:
        sync_interval: Seconds between synchronization cycles.

    Returns:
        int: Cycle count covering EMPTY_RESPONSE_CONFIRM_SECONDS, never fewer than 2 —
            a single empty response must never be enough, however long the interval.
    """
    return max(2, math.ceil(EMPTY_RESPONSE_CONFIRM_SECONDS / max(1, sync_interval)))


@dataclass
class _AliasGuardState:
    """Per-alias memory the removal guards carry between synchronization cycles.

    Kept as ONE object per alias so a new branch in the sync loop cannot reset half of
    it: `reset()` clears everything a cycle that proved nothing must forget, and the two
    narrower resets state exactly which half they drop.

    Attributes:
        empty_cycles: Consecutive empty-but-successful responses seen so far.
        empty_alerted: Whether the empty-response alert reached an admin (dedupe).
        pending: Missing composite keys whose removal awaits confirmation.
        deferral_cycles: Consecutive cycles this alias has been deferring a removal.
        mass_alerted: Whether the deferred-removal alert reached an admin (dedupe).
    """

    empty_cycles: int = 0
    empty_alerted: bool = False
    pending: frozenset[str] = field(default_factory=frozenset)
    deferral_cycles: int = 0
    mass_alerted: bool = False

    def reset_empty(self) -> None:
        """Clear the empty-response streak and its delivery-deduplication state.

        Returns:
            None.
        """
        self.empty_cycles = 0
        self.empty_alerted = False

    def reset_removal(self) -> None:
        """Forget a deferred removal that was confirmed, withdrawn, or unconfirmable.

        Returns:
            None.
        """
        self.pending = frozenset()
        self.deferral_cycles = 0
        self.mass_alerted = False

    def reset(self) -> None:
        """Forget all guard evidence after an uninformative provider cycle.

        Returns:
            None.
        """
        self.reset_empty()
        self.reset_removal()


def _group_keys_by_alias(servers: list[Any]) -> dict[str, set[str]]:
    """Group server composite keys by provider alias.

    Args:
        servers: Server models (local or freshly fetched from the providers).

    Returns:
        dict[str, set[str]]: alias -> set of composite keys belonging to it.
    """
    grouped: dict[str, set[str]] = {}
    for server in servers:
        grouped.setdefault(server.effective_alias, set()).add(server.composite_key)
    return grouped


def _provider_label(config: Any, alias: str) -> str:
    """Return the human-readable provider name used in admin notifications.

    Args:
        config: Provider instance configuration (may carry a display_name).
        alias: Provider alias, used as the fallback label.

    Returns:
        str: display_name when set, otherwise the upper-cased alias.
    """
    return getattr(config, "display_name", "") or alias.upper()


async def _observe_empty_response(
    *,
    bot: Bot,
    admin_ids: list[int],
    alias: str,
    provider_label: str,
    local_keys: set[str],
    state: _AliasGuardState,
    confirm_cycles: int,
) -> bool:
    """Decide whether an EMPTY provider response may be acted on (GUARD A1).

    An empty-but-successful response is what a provider outage looks like when its API
    answers 200 with no data — acting on the first one cost this bot a whole fleet's
    monitoring history. So emptiness must persist for `confirm_cycles` consecutive cycles
    before it is believed; until then the caller skips the alias entirely and the admins
    are alerted once (deduplicated on DELIVERED sends only).

    Args:
        bot: aiogram Bot instance used to send messages.
        admin_ids: List of administrator IDs to notify.
        alias: Provider alias that answered with nothing.
        provider_label: Human-readable provider name for the alert.
        local_keys: Composite keys currently known locally for that alias.
        state: The alias's guard state (mutated: the empty streak advances here).
        confirm_cycles: Consecutive empty responses required to believe the emptiness.

    Returns:
        bool: True if the emptiness is confirmed and its removals may proceed; False if
            the alias must be skipped this cycle.
    """
    state.empty_cycles += 1
    # An empty response says nothing about which servers are missing, so it can never
    # confirm a deferred removal.
    state.reset_removal()

    if state.empty_cycles >= confirm_cycles:
        logger.warning(
            f"Provider {alias} has returned an EMPTY server list for {state.empty_cycles} "
            f"consecutive cycles; accepting it as a real empty account and removing its "
            f"{len(local_keys)} servers"
        )
        return True

    logger.error(
        f"Provider {alias} returned an EMPTY server list while {len(local_keys)} servers "
        f"are known locally ({state.empty_cycles}/{confirm_cycles}); skipping removal"
    )
    if not state.empty_alerted:
        # Arm the dedupe only on a confirmed delivery, so a failed send is retried.
        state.empty_alerted = await send_suspicious_api_response_notification(
            bot=bot,
            admin_ids=admin_ids,
            provider_label=provider_label,
            local_count=len(local_keys),
        )
    return False


async def _authorize_removals(
    *,
    bot: Bot,
    admin_ids: list[int],
    responded_aliases: set[str],
    confirmed_empty_aliases: set[str],
    local_by_alias: dict[str, set[str]],
    api_by_alias: dict[str, set[str]],
    guard_state: dict[str, _AliasGuardState],
    provider_labels: dict[str, str],
    max_removal_ratio: float,
) -> set[str]:
    """Decide which providers may have servers removed this cycle (GUARD A2).

    A provider that suddenly stops reporting a large share of its fleet is far more often
    returning a truncated list than reporting a real mass deletion, so such a removal is
    DEFERRED: it is applied only once the next cycle reports the identical missing set. A
    small removal — a server the user really did delete — is never delayed.

    Args:
        bot: aiogram Bot instance used to send messages.
        admin_ids: List of administrator IDs to notify.
        responded_aliases: Aliases that answered this cycle.
        confirmed_empty_aliases: Aliases whose emptiness guard A1 already confirmed over
            several cycles. They skip this guard: their whole fleet is missing by
            definition, and demanding a second confirmation of the same fact would defer
            the removal forever (A1 clears the pending set on every empty response).
        local_by_alias: alias -> composite keys known locally.
        api_by_alias: alias -> composite keys the providers just reported.
        guard_state: Per-alias guard memory (mutated: deferrals advance here).
        provider_labels: alias -> human-readable name, for the alerts.
        max_removal_ratio: Share of a fleet above which a removal must be confirmed.

    Returns:
        set[str]: Aliases whose removals may be applied now.
    """
    authorized = set(responded_aliases)

    for alias in sorted(responded_aliases):
        local_keys = local_by_alias.get(alias, set())
        state = guard_state.setdefault(alias, _AliasGuardState())
        if not local_keys or alias in confirmed_empty_aliases:
            state.reset_removal()
            continue

        missing = frozenset(local_keys - api_by_alias.get(alias, set()))
        is_mass_removal = (
            len(missing) >= MIN_DEFERRABLE_REMOVALS
            and len(missing) / len(local_keys) > max_removal_ratio
        )
        if not missing or not is_mass_removal:
            state.reset_removal()
            continue

        if state.pending == missing:
            # An identical second observation satisfies the guard's authorization rule.
            logger.warning(
                f"Sync: confirmed removal of {len(missing)} servers from {alias} "
                f"after a deferral cycle"
            )
            state.reset_removal()
            continue

        # First sighting, or the missing set changed: defer and re-arm.
        state.pending = missing
        state.deferral_cycles += 1
        authorized.discard(alias)
        logger.warning(
            f"Sync: deferring removal of {len(missing)}/{len(local_keys)} servers from "
            f"{alias} until the next cycle confirms it"
        )
        if state.deferral_cycles >= DEFERRAL_WARN_CYCLES:
            logger.error(
                f"Sync: {alias} has been deferring a mass removal for "
                f"{state.deferral_cycles} cycles — the missing set keeps changing"
            )
        if not state.mass_alerted:
            # Arm the dedupe only on a confirmed delivery, so a failed alert is retried.
            state.mass_alerted = await send_mass_removal_deferred_notification(
                bot=bot,
                admin_ids=admin_ids,
                provider_label=provider_labels.get(alias, alias.upper()),
                removal_count=len(missing),
                total_count=len(local_keys),
            )

    return authorized


async def servers_sync_task(
    bot: Bot,
    provider_manager: Any,  # ProviderManager
    servers_repo: ServersRepository,
    stats_repo: SqliteStatisticsRepository,
    ping_manager: Any,  # PingManager
    admin_ids: list[int],
    sync_interval: int = 1800,
    max_removal_ratio: float = 0.3,
    heartbeat: Callable[[], None] = lambda: None,
) -> None:
    """
    Background task that automatically synchronizes servers with provider APIs.

    Runs in an infinite loop at the given interval and:
    1. Fetches the current server list from every provider
    2. Synchronizes it with local storage (add/remove/update)
    3. Manages monitoring worker processes (start/stop)
    4. Sends notifications to administrators about changes
    5. Tombstones the statistics of removed servers (physically purged only after the
       repository's grace window) and drops their in-memory alert/schedule state, while
       preserving their persisted check configuration

    Removal is guarded against untrustworthy provider responses, which is what a provider
    outage often looks like — HTTP 200 with a truncated or empty list rather than an error:
    - An alias whose response is EMPTY while servers are known locally removes nothing and
      alerts the admins instead — until the emptiness has held for
      EMPTY_RESPONSE_CONFIRM_SECONDS, at which point an actually-emptied account stops
      being indistinguishable from an outage and the removal proceeds (_observe_empty_response).
    - An alias losing at least MIN_DEFERRABLE_REMOVALS servers AND more than
      max_removal_ratio of its fleet in one cycle has that removal DEFERRED until the next
      cycle reports the identical missing set. A failed fetch or unconfirmed empty response
      clears the evidence; a different missing set starts confirmation over for that set
      while the alias remains in a continuous deferral streak.

    Provider availability alerting is debounced: transient failures
    (5xx/timeout/rate-limit) only alert once they become a sustained outage
    (>= OUTAGE_ALERT_THRESHOLD consecutive failures), while persistent errors
    (auth/permissions) alert immediately. A recovery notification is sent when a
    provider with an open incident responds again. An unconfirmed empty response does NOT
    count as recovery; an empty response accepted after the full guard threshold does.
    Per-alias alert and deferral state lives in memory across loop iterations, so a
    supervisor-driven task restart costs at most one extra confirmation cycle (and may
    repeat an alert).

    Args:
        bot: aiogram Bot instance used to send messages.
        provider_manager: Manager of all cloud providers (ProviderManager).
        servers_repo: Server repository.
        stats_repo: SQLite statistics repository.
        ping_manager: Manager of monitoring worker processes (PingManager).
        admin_ids: List of administrator IDs to notify.
        sync_interval: Synchronization interval in seconds (default 1800 = 30 minutes).
        max_removal_ratio: Share of an alias's servers whose simultaneous disappearance
            makes a removal suspicious enough to defer for one cycle.
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
    # Removal-guard memory, one object per alias (see _AliasGuardState). Alert dedupe
    # inside it is armed only after a DELIVERED send, so a failed alert is retried next
    # cycle — the same delivery-confirmed rule the ping and balance alerts follow.
    guard_state: dict[str, _AliasGuardState] = {}
    empty_confirm_cycles = _empty_confirm_cycles(sync_interval)

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

                # Snapshot of what is known locally, per alias. Both removal guards below
                # compare the API response against it; nothing else re-reads the repo.
                local_servers = servers_repo.get_all()
                local_by_alias = _group_keys_by_alias(local_servers)
                # Aliases whose emptiness held long enough to be believed THIS cycle; they
                # are the only ones allowed past the repository's empty-response floor.
                confirmed_empty_aliases: set[str] = set()

                for idx, alias in enumerate(alias_order):
                    provider, config = providers_dict[alias]
                    result = results[idx]

                    provider_label = _provider_label(config, alias)
                    state = guard_state.setdefault(alias, _AliasGuardState())

                    if isinstance(result, Exception):
                        logger.error(
                            f"Failed to fetch servers from {alias}: {result}",
                            exc_info=result,
                        )

                        failures = consecutive_failures.get(alias, 0) + 1
                        consecutive_failures[alias] = failures

                        # A cycle that could not compare anything cannot confirm a
                        # deferred removal or an empty account either: both confirmations
                        # must be CONSECUTIVE.
                        state.reset()

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
                        local_keys = local_by_alias.get(alias, set())

                        # GUARD A1 (see _observe_empty_response): an empty list while
                        # servers are known locally is far more likely a provider glitch
                        # wearing a 200 than an emptied account.
                        if not result and local_keys:
                            confirmed = await _observe_empty_response(
                                bot=bot,
                                admin_ids=admin_ids,
                                alias=alias,
                                provider_label=provider_label,
                                local_keys=local_keys,
                                state=state,
                                confirm_cycles=empty_confirm_cycles,
                            )
                            if not confirmed:
                                continue
                            # Emptiness outlasted any plausible outage: let the removal
                            # through (confirmed_empty_aliases lifts the repository's own
                            # empty-response floor for this alias).
                            confirmed_empty_aliases.add(alias)
                        else:
                            state.reset_empty()

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

                # If no provider responded, skip this synchronization entirely.
                if not successful_aliases:
                    logger.error(
                        "Failed to fetch servers from all providers, skipping synchronization"
                    )
                    continue

                # GUARD A2: an alias losing a large share of its fleet in ONE cycle has that
                # removal deferred until the NEXT cycle reports the identical missing set.
                # A genuine deletion survives that wait; a truncated API response does not.
                # Removal authorization is tracked SEPARATELY from "the provider answered":
                # a deferred alias still gets its additions and updates applied.
                removal_authorized = await _authorize_removals(
                    bot=bot,
                    admin_ids=admin_ids,
                    responded_aliases=successful_aliases,
                    confirmed_empty_aliases=confirmed_empty_aliases,
                    local_by_alias=local_by_alias,
                    api_by_alias=_group_keys_by_alias(all_servers),
                    guard_state=guard_state,
                    provider_labels={
                        alias: _provider_label(providers_dict[alias][1], alias)
                        for alias in successful_aliases
                    },
                    max_removal_ratio=max_removal_ratio,
                )

                # Synchronize with local storage. Only removal_authorized aliases may lose
                # servers; every responding provider still contributes additions/updates.
                sync_result = servers_repo.sync_with_api_servers(
                    all_servers,
                    successful_aliases=removal_authorized,
                    empty_ok_aliases=confirmed_empty_aliases,
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

                # Every added server exists again, so drop its tombstone — one batched
                # write for the whole set, before anything below can fail per server.
                if added_servers:
                    try:
                        revived = stats_repo.unmark_servers_deleted(
                            [server.composite_key for server in added_servers]
                        )
                        if revived:
                            logger.info(
                                f"{revived} servers returned within the grace window; their "
                                f"statistics history is preserved"
                            )
                    except Exception as e:
                        logger.error(
                            f"Failed to clear statistics tombstones for returning servers: {e}",
                            exc_info=True,
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

                    # Tombstone the statistics instead of deleting them now: the removal may
                    # still turn out to be a provider glitch that the guards did not catch,
                    # and a server that comes back within the grace window keeps its history.
                    try:
                        stats_repo.mark_server_deleted(composite_key)
                    except Exception as e:
                        logger.error(
                            f"Failed to tombstone statistics for {composite_key}: {e}",
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

                # Physically purge the statistics of servers tombstoned past the grace
                # window. Driven from here rather than from a statistics writer: removing
                # the last enabled server also removes every ping batch, and a purge riding
                # on writes would then never run. The repository rate-limits it internally.
                # Off the event loop: one purge can delete the rows of a whole fleet at
                # once while holding the statistics lock the batch writers need. The
                # present-key list is built from this cycle's snapshot plus whatever was
                # just added — no second read of the server repository.
                present_keys = [key for keys in local_by_alias.values() for key in keys]
                present_keys.extend(server.composite_key for server in added_servers)
                try:
                    await asyncio.to_thread(stats_repo.purge_expired_deleted, present_keys)
                except Exception as e:
                    logger.error(f"Failed to purge expired statistics: {e}", exc_info=True)

            except Exception as e:
                logger.error(f"Error in servers sync cycle: {e}", exc_info=True)
                # Keep running even after an error

    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error(f"Critical error in servers sync task: {e}", exc_info=True)
        raise
