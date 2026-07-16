"""Supervised background task that runs per-server TCP/HTTP/SSL service checks.

Runs in the bot's MAIN process (not the ICMP ping workers): it reads the per-server check
config from the in-process store each cycle, runs the due checks concurrently, writes their
    results directly to the stats DB (no IPC), and alerts admins. Every check type has an
    edge-triggered reachability axis (transition down/up); SSL checks additionally have a
    level-triggered certificate axis (one per cooldown window while a certificate is
    expiring/invalid). Thus an unreachable SSL endpoint alerts on the reachability axis.

    Each cycle reschedules due checks before awaiting them, then accepts results only after
    re-validating the check's enabled state and the server's current existence and IP. Failed
    DB writes stay in a bounded retry buffer. Repeated whole-cycle failures are tolerated up
    to a fixed limit, then re-raised so the supervisor can restart the task.

The module function is named ``service_checks_task`` — the ``_task`` suffix matters: the
package ``__init__`` re-exports task FUNCTIONS, shadowing like-named submodules, so a bare
``service_checks`` name would make ``from ...background_tasks import service_checks`` yield
the function, breaking any test that needs the module.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

from aiogram import Bot

from ..bot.notifications import (
    send_check_down_notification,
    send_check_up_notification,
    send_checks_rollup_notification,
    send_ssl_expiry_notification,
)
from ..checks import (
    check_http_endpoint,
    check_ssl_expiry,
    check_tcp_port,
    format_host_port,
    resolve_target,
)
from ..checks.outcome import CheckOutcome
from ..models.server import Server
from ..models.service_check import CheckDefinition, CheckStatus, CheckType, ServiceCheckResult

logger = logging.getLogger(__name__)

# Max concurrent checks per cycle — bounds the first-cycle "everything is due" burst and the
# steady-state load on the event loop shared with aiogram polling.
MAX_CONCURRENCY = 20

# Per-check-and-direction anti-flap cooldown for TCP/HTTP alerts (mirrors the ping path).
CHECK_NOTIFICATION_COOLDOWN_SECONDS = 300

# Level-triggered SSL alert window: at most one alert per this long while a cert stays
# expiring/invalid (mirrors the low-balance alert cadence). Re-armed when the cert recovers.
SSL_ALERT_COOLDOWN_SECONDS = 24 * 60 * 60

# When more than this many checks newly fail in ONE cycle, send a single roll-up alert
# instead of N individual ones so a fleet-wide failure cannot flood the bot transport that
# ICMP up/down alerts also use.
ROLLUP_THRESHOLD = 5

# After this many consecutive whole-cycle failures the task re-raises so the supervisor
# restarts it (and ultimately alerts): a deterministic failure would otherwise keep beating
# the heartbeat every cycle and look healthy forever while doing no useful work.
MAX_CONSECUTIVE_CYCLE_FAILURES = 5

# Hard cap on the DB-write retry buffer so a sustained DB outage cannot grow it without bound
# and exhaust the process (mirrors the ping processor's emergency batch cap).
MAX_PENDING_RESULTS = 5000

# --- Per-check state (module-level; single-process, main-process only) ---

# Monotonic deadline of the next run per (composite_key, check_id). ABSOLUTE deadlines: a
# check runs when now >= its deadline, and before the concurrent gather its deadline is set
# to now + interval. Rescheduling first preserves a concurrent mark_check_dirty() call made
# while the probe is in flight. (A relative "+= interval" from a 0.0 default would leave the
# deadline in the past forever, firing every check every cycle.)
_next_run_at: dict[tuple[str, str], float] = {}

# Last check status SUCCESSFULLY delivered to admins per (composite_key, check_id): "ok" /
# "failed" / "unknown". Advanced only on confirmed delivery, so an undelivered alert retries.
# Kept SEPARATE from ping_processor's dicts — sharing them would let a failing HTTP check
# suppress a genuine ICMP down alert for the same server.
_last_notified_check_status: dict[tuple[str, str], str] = {}

# Wall-clock time of the last delivered TCP/HTTP alert per (composite_key, check_id, direction),
# so a recovery alert is never throttled by a recent failure alert and vice-versa.
_last_check_notification_time: dict[tuple[str, str, str], float] = {}

# Wall-clock time of the last delivered SSL level alert per (composite_key, check_id).
_last_ssl_alert_at: dict[tuple[str, str], float] = {}


def reset_ssl_alert_for(composite_key: str, check_id: str) -> None:
    """Re-arm the SSL level alert for one check so its next expiring/invalid result alerts now.

    Called when an admin edits an SSL check's warning window or re-enables it, so a change is
    reflected promptly instead of waiting out the leftover 24h cooldown. Per-check (not a
    fleet-wide clear): editing one check must not re-alert every other server's certificate.

    Args:
        composite_key: The server's composite key.
        check_id: The SSL check to re-arm.

    Returns:
        None.
    """
    _last_ssl_alert_at.pop((composite_key, check_id), None)


def mark_check_dirty(composite_key: str, check_id: str) -> None:
    """Force a check to run promptly and re-evaluate its alert state after a config change.

    Called by the checks router after adding, editing, or re-enabling a check: the check
    becomes due on the next cycle, its suppressed down/up state is cleared (so a still-failing
    re-enabled check alerts again), and its SSL cooldown is re-armed.

    Args:
        composite_key: The server's composite key.
        check_id: The check that changed.

    Returns:
        None.
    """
    key = (composite_key, check_id)
    _next_run_at[key] = 0.0  # < any monotonic value -> due next cycle
    _last_notified_check_status.pop(key, None)
    reset_ssl_alert_for(composite_key, check_id)


def _drop_state_where(should_drop: Callable[[tuple], bool]) -> None:
    """Delete entries from every per-check state dict whose key matches a predicate.

    All four state dicts are keyed by a tuple whose first two elements are
    (composite_key, check_id); the predicate only ever inspects those, so it applies
    uniformly to the 2-tuple dicts and the 3-tuple notification-time dict.

    Args:
        should_drop: Predicate over a state-dict key; True deletes that entry.

    Returns:
        None.
    """
    # The dicts have different key arities (2- vs 3-tuple), so type the collection as
    # heterogeneous; should_drop only inspects the shared leading elements.
    states: tuple[dict[Any, Any], ...] = (
        _next_run_at,
        _last_notified_check_status,
        _last_ssl_alert_at,
        _last_check_notification_time,
    )
    for state in states:
        for key in [k for k in state if should_drop(k)]:
            del state[key]


def forget_server_checks(server_key: str) -> None:
    """Drop all in-memory check state for a removed server (an iterating prune).

    The state dicts are tuple-keyed by (composite_key, check_id[, direction]); a bare
    ``.pop(server_key)`` would never match, leaking entries across fleet churn and letting a
    re-added server inherit stale state. This does NOT touch the persisted check config — a
    provider returning an erroneous empty list must not vaporize a user's hand-built checks.

    Args:
        server_key: Composite key of the removed server.

    Returns:
        None.
    """
    _drop_state_where(lambda k: k[0] == server_key)


def _prune_stale_state(live_keys: set[tuple[str, str]]) -> None:
    """Self-healing prune of state for checks no longer in the config.

    Complements forget_server_checks: a check DELETED from a still-present server (or any
    entry the explicit prune missed) is dropped here so the state dicts track the live config.

    Args:
        live_keys: The (composite_key, check_id) pairs present in the current config.

    Returns:
        None.
    """
    _drop_state_where(lambda k: (k[0], k[1]) not in live_keys)


def _interval_for(check: CheckDefinition, check_interval: int, ssl_interval: int) -> int:
    """Return a check's run interval: the SSL interval for SSL checks, else the default.

    Args:
        check: The check.
        check_interval: Default (TCP/HTTP) interval in seconds.
        ssl_interval: SSL interval in seconds.

    Returns:
        int: The interval to use for this check.
    """
    return ssl_interval if check.type == CheckType.SSL else check_interval


def _describe_check(check: CheckDefinition, server: Server) -> str:
    """Build a compact technical descriptor of a check for alert messages.

    Args:
        check: The check definition.
        server: The server the check targets.

    Returns:
        str: e.g. "TCP 1.2.3.4:443", "HTTP https://x/health", "SSL [2a01::1]:443".
    """
    if check.type == CheckType.HTTP:
        return f"HTTP {check.url or '?'}"
    return f"{check.type.value.upper()} {format_host_port(server.ip, check.effective_port)}"


async def _run_one_check(
    check: CheckDefinition,
    server: Server,
    *,
    http_client,
    tcp_timeout: float,
    http_timeout: float,
    ssl_warn_days: int,
) -> CheckOutcome | None:
    """Run a single check, returning its outcome or None when it must be skipped.

    Skips (returns None) a misconfigured check or one whose target address is unsafe
    (0.0.0.0/loopback), so a dead server can never read healthy.

    Args:
        check: The check to run.
        server: The server it targets.
        http_client: The shared httpx client (HTTP checks).
        tcp_timeout: TCP connect timeout in seconds.
        http_timeout: HTTP request / SSL handshake timeout in seconds.
        ssl_warn_days: Global SSL warn-days default (overridden per check).

    Returns:
        CheckOutcome | None: The result, or None when skipped.
    """
    if check.type == CheckType.HTTP:
        if not check.url:
            return None
        return await check_http_endpoint(
            http_client,
            check.url,
            expected_status=check.expected_status,
            keyword=check.keyword,
            timeout=http_timeout,
        )

    # TCP and SSL need the server's address; validate it once.
    if resolve_target(server.ip) is None:
        logger.debug("Skipping %s check for %s: unsafe/absent address %r",
                     check.type.value, server.composite_key, server.ip)
        return None

    if check.type == CheckType.TCP:
        if check.port is None:
            return None
        return await check_tcp_port(server.ip, check.port, tcp_timeout)

    # SSL
    warn_days = check.warn_days if check.warn_days is not None else ssl_warn_days
    return await check_ssl_expiry(
        server.ip, check.effective_port, warn_days=warn_days, timeout=http_timeout
    )


def _flush_pending(stats_repo, pending: list[ServiceCheckResult]) -> list[ServiceCheckResult]:
    """Write accumulated check results, retaining them for retry on a DB error.

    Mirrors the ping processor's re-queue-on-failure: a transient DB error must not silently
    lose a cycle's results. Runs in a worker thread (called via asyncio.to_thread).

    Args:
        stats_repo: The statistics repository.
        pending: All results accumulated so far (this cycle plus any retained).

    Returns:
        list[ServiceCheckResult]: Empty on success. On failure, the retained results, capped
            at ``MAX_PENDING_RESULTS`` by dropping the oldest overflow entries.
    """
    if not pending:
        return []
    try:
        stats_repo.add_check_batch(pending)
        return []
    except Exception as e:
        if len(pending) > MAX_PENDING_RESULTS:
            dropped = len(pending) - MAX_PENDING_RESULTS
            logger.error(
                "Service-check retry buffer exceeded %d during a DB outage; dropping %d oldest "
                "result(s): %s", MAX_PENDING_RESULTS, dropped, e,
            )
            return pending[-MAX_PENDING_RESULTS:]
        logger.error(
            "Failed to write service-check batch (retaining %d for retry): %s", len(pending), e
        )
        return pending


async def service_checks_task(
    *,
    bot: Bot,
    servers_repo,
    stats_repo,
    http_client,
    admin_ids: list[int],
    check_interval: int,
    ssl_interval: int,
    ssl_warn_days: int,
    tcp_timeout: int,
    http_timeout: int,
    checks_getter: Callable[[], dict[str, list[CheckDefinition]]],
    heartbeat: Callable[[], None] = lambda: None,
) -> None:
    """Run due service checks forever, writing stats and alerting admins each cycle.

    Due probes are concurrency-limited and rescheduled before they run. Completed results are
    persisted and alerted only after fresh config/server/IP validation. Database failures are
    retried through a bounded pending-results buffer. A successful cycle resets the failure
    counter; after ``MAX_CONSECUTIVE_CYCLE_FAILURES`` consecutive cycle exceptions, the last
    exception is re-raised so the supervisor can recreate the task.

    Args:
        bot: aiogram Bot for alerts.
        servers_repo: Servers repository (to resolve a check's target server).
        stats_repo: Statistics repository (add_check_batch, direct — no IPC).
        http_client: Shared httpx client for HTTP checks.
        admin_ids: Administrator IDs to alert.
        check_interval: Wake cadence and default TCP/HTTP check interval, seconds.
        ssl_interval: SSL check interval, seconds (certs rotate slowly).
        ssl_warn_days: Global default days-before-expiry to warn.
        tcp_timeout: TCP connect timeout, seconds.
        http_timeout: HTTP request / SSL handshake timeout, seconds.
        checks_getter: Returns the current {composite_key: [CheckDefinition]} snapshot.
        heartbeat: Progress callback; called at cycle top AND after each completed check.

    Returns:
        None. Runs until cancelled (a clean return is treated as a crash by the supervisor).

    Raises:
        asyncio.CancelledError: Re-raised when task cancellation is requested.
        Exception: Re-raised after the configured consecutive whole-cycle failure limit.
    """
    pending: list[ServiceCheckResult] = []
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    consecutive_failures = 0
    logger.info("Service-checks task started (interval=%ss, ssl_interval=%ss)", check_interval, ssl_interval)

    while True:
        try:
            heartbeat()  # top-of-cycle beat: guarantees a beat every interval even when idle
            pending = await _run_cycle(
                bot=bot,
                servers_repo=servers_repo,
                stats_repo=stats_repo,
                http_client=http_client,
                admin_ids=admin_ids,
                check_interval=check_interval,
                ssl_interval=ssl_interval,
                ssl_warn_days=ssl_warn_days,
                tcp_timeout=tcp_timeout,
                http_timeout=http_timeout,
                checks_getter=checks_getter,
                heartbeat=heartbeat,
                semaphore=semaphore,
                pending=pending,
            )
            consecutive_failures = 0
        except asyncio.CancelledError:
            raise
        except Exception:
            consecutive_failures += 1
            logger.exception(
                "Service-checks cycle failed (%d consecutive); continuing", consecutive_failures
            )
            if consecutive_failures >= MAX_CONSECUTIVE_CYCLE_FAILURES:
                # A deterministic failure keeps beating the heartbeat and would look healthy
                # forever; re-raise so the supervisor restarts the task (and ultimately alerts).
                logger.error(
                    "Service-checks task failed %d cycles in a row; re-raising for restart",
                    consecutive_failures,
                )
                raise
        await asyncio.sleep(check_interval)


async def _run_cycle(
    *,
    bot: Bot,
    servers_repo,
    stats_repo,
    http_client,
    admin_ids: list[int],
    check_interval: int,
    ssl_interval: int,
    ssl_warn_days: int,
    tcp_timeout: int,
    http_timeout: int,
    checks_getter: Callable[[], dict[str, list[CheckDefinition]]],
    heartbeat: Callable[[], None],
    semaphore: asyncio.Semaphore,
    pending: list[ServiceCheckResult],
) -> list[ServiceCheckResult]:
    """Run one full cycle with pre-run rescheduling and post-run live-state validation.

    Due checks receive their next deadline before ``gather`` so a concurrent dirty mark is
    preserved. After probing, deleted/disabled checks, removed servers, and results for a
    superseded server IP are discarded before persistence and alerting. DB failures return a
    bounded retry buffer for the next cycle.

    Args:
        bot: aiogram Bot used for notifications.
        servers_repo: Repository used for cycle-top and post-run live server snapshots.
        stats_repo: Statistics repository used by the batch writer.
        http_client: Shared httpx client for HTTP checks.
        admin_ids: Administrator IDs to alert.
        check_interval: TCP/HTTP interval and outer-loop wake cadence, in seconds.
        ssl_interval: SSL check interval in seconds.
        ssl_warn_days: Global certificate-expiry warning window in days.
        tcp_timeout: TCP connect timeout in seconds.
        http_timeout: HTTP deadline and SSL handshake timeout in seconds.
        checks_getter: Callable returning the current service-check configuration snapshot.
        heartbeat: Progress callback invoked after probes and notification sends.
        semaphore: Concurrency limiter shared by all probes in the task.
        pending: Results retained from a previous failed database write.

    Returns:
        list[ServiceCheckResult]: Results retained for retry (empty on a clean DB write).
    """
    now = time.monotonic()
    config = checks_getter()
    servers = {s.composite_key: s for s in servers_repo.get_all()}
    live_keys = {(ck, c.check_id) for ck, checks in config.items() for c in checks}

    # Select due checks (and schedule first sightings with a small stagger).
    due: list[tuple[Server, CheckDefinition]] = []
    stagger = 0
    for composite_key, checks in config.items():
        server = servers.get(composite_key)
        if server is None:
            continue  # config lingers for a server not currently present; skip quietly
        for check in checks:
            if not check.enabled:
                continue
            key = (composite_key, check.check_id)
            interval = _interval_for(check, check_interval, ssl_interval)
            due_at = _next_run_at.get(key)
            if due_at is None:
                # First sighting: stagger the first run across the interval so a big fleet
                # does not all fire at once (the semaphore also bounds this).
                _next_run_at[key] = now + (stagger % max(1, interval))
                stagger += 1
                continue
            if now >= due_at:
                due.append((server, check))

    # Run due checks concurrently, beating the heartbeat after each completes.
    async def run(server: Server, check: CheckDefinition):
        """Run one due check under the semaphore and convert unexpected errors to outcomes.

        Args:
            server: Cycle-top server snapshot targeted by the check.
            check: Due check definition.

        Returns:
            tuple: The server, check, and resulting ``CheckOutcome`` (or None when skipped).
        """
        async with semaphore:
            try:
                outcome = await _run_one_check(
                    check, server,
                    http_client=http_client,
                    tcp_timeout=tcp_timeout,
                    http_timeout=http_timeout,
                    ssl_warn_days=ssl_warn_days,
                )
            except Exception as e:
                logger.exception("Check %s for %s raised", check.check_id, server.composite_key)
                outcome = CheckOutcome(status=CheckStatus.FAILED, error=str(e))
            heartbeat()
            return server, check, outcome

    # Reschedule every due check to its next absolute deadline BEFORE running it, so a
    # concurrent mark_check_dirty() during the gather await (an admin editing/re-enabling the
    # check) that forces a "run now" is not clobbered by a post-gather reschedule.
    for server, check in due:
        _next_run_at[(server.composite_key, check.check_id)] = now + _interval_for(
            check, check_interval, ssl_interval
        )

    ran = await asyncio.gather(*(run(s, c) for s, c in due), return_exceptions=True)

    # Re-validate against FRESH state: a check deleted or DISABLED, or a server removed, mid-
    # cycle must not have its stale in-flight result persisted (recreating cleared history) or
    # alerted. Server removal deliberately PRESERVES check config, so liveness is checked too.
    fresh = checks_getter()
    fresh_enabled_keys = {
        (ck, c.check_id) for ck, checks in fresh.items() for c in checks if c.enabled
    }
    fresh_servers = {s.composite_key: s for s in servers_repo.get_all()}

    results: list[tuple[Server, CheckDefinition, CheckOutcome]] = []
    for item in ran:
        if isinstance(item, BaseException):
            continue
        server, check, outcome = item
        if outcome is None:
            continue
        # Skip a result whose server was removed OR whose target IP was reassigned mid-probe:
        # a stale-IP outcome must not be persisted or alerted.
        fresh_server = fresh_servers.get(server.composite_key)
        if fresh_server is None:
            continue
        if fresh_server.ip != server.ip:
            # The address changed under us (the deadline was already advanced before the
            # gather); force a prompt re-probe of the NEW IP instead of waiting a full interval
            # (up to the SSL interval), then drop the stale-IP result.
            _next_run_at[(server.composite_key, check.check_id)] = 0.0
            continue
        if (server.composite_key, check.check_id) not in fresh_enabled_keys:
            continue
        results.append((server, check, outcome))

    # Persist (retain-and-retry on DB error).
    for server, check, outcome in results:
        pending.append(
            ServiceCheckResult(
                server_id=server.id,
                provider_alias=server.effective_alias,
                check_id=check.check_id,
                type=check.type,
                status=outcome.status,
                latency_ms=outcome.latency_ms,
                error=outcome.error,
                days_until_expiry=outcome.days_until_expiry,
                not_after=outcome.not_after,
            )
        )
    if pending:
        pending = await asyncio.to_thread(_flush_pending, stats_repo, pending)

    # Alerts, sent SEQUENTIALLY after the concurrent run (heartbeating between sends so a long
    # alert sequence cannot look like a stall).
    await _process_alerts(bot, admin_ids, results, heartbeat)

    # Prune against a snapshot taken RIGHT HERE (no await since), unioned with the cycle-top
    # keys: a check added during this cycle's flush/alert awaits keeps its mark_check_dirty
    # "run now" schedule, and a check removed mid-cycle is cleaned once it is in neither.
    final_keys = {(ck, c.check_id) for ck, checks in checks_getter().items() for c in checks}
    _prune_stale_state(live_keys | final_keys)
    return pending


def _cooldown_ok(key: tuple[str, str], direction: str, now_wall: float) -> bool:
    """Return whether the per-direction anti-flap cooldown has elapsed for a check.

    Args:
        key: (composite_key, check_id).
        direction: "down" or "up".
        now_wall: Current wall-clock time.

    Returns:
        bool: True if an alert may be sent now.
    """
    last = _last_check_notification_time.get((key[0], key[1], direction))
    return last is None or (now_wall - last) >= CHECK_NOTIFICATION_COOLDOWN_SECONDS


async def _process_alerts(
    bot: Bot,
    admin_ids: list[int],
    results: list[tuple[Server, CheckDefinition, CheckOutcome]],
    heartbeat: Callable[[], None],
) -> None:
    """Send reachability (edge) and SSL-certificate (level) alerts, sequentially.

    Every check type has a REACHABILITY axis (edge-triggered down/up). SSL checks additionally
    have a CERTIFICATE axis (level-triggered expiring/invalid): a cert problem is reported via
    the level axis, an unreachable SSL endpoint via the edge axis — so a down SSL endpoint is
    never silent. Down alerts roll up into ONE message past ROLLUP_THRESHOLD; the heartbeat
    beats between sends so a long alert sequence cannot look like a stall. Every state advance
    is gated on confirmed delivery.

    Args:
        bot: aiogram Bot.
        admin_ids: Administrator IDs.
        results: The cycle's (server, check, outcome) triples (already re-validated).
        heartbeat: Progress callback, beaten after each alert send.

    Returns:
        None.
    """
    now_wall = time.time()
    down_events: list[tuple[Server, CheckDefinition, CheckOutcome]] = []
    up_events: list[tuple[Server, CheckDefinition, CheckOutcome]] = []
    ssl_events: list[tuple[Server, CheckDefinition, CheckOutcome]] = []

    for server, check, outcome in results:
        key = (server.composite_key, check.check_id)

        if check.type == CheckType.SSL:
            # Certificate axis (level-triggered), independent of reachability.
            if outcome.status in (CheckStatus.CERT_EXPIRING, CheckStatus.CERT_INVALID):
                if now_wall - _last_ssl_alert_at.get(key, 0.0) >= SSL_ALERT_COOLDOWN_SECONDS:
                    ssl_events.append((server, check, outcome))
            elif outcome.status == CheckStatus.OK:
                _last_ssl_alert_at.pop(key, None)  # cert genuinely healthy -> re-arm
            # TIMEOUT/FAILED: unreachable, so the cert can't be assessed -> leave cooldown as-is.
            reachable = outcome.status in (
                CheckStatus.OK, CheckStatus.CERT_EXPIRING, CheckStatus.CERT_INVALID
            )
        else:
            reachable = outcome.status == CheckStatus.OK

        # Reachability axis (edge-triggered down/up), shared across all check types.
        prev = _last_notified_check_status.get(key, "unknown")
        if not reachable and prev != "failed" and _cooldown_ok(key, "down", now_wall):
            down_events.append((server, check, outcome))
        elif reachable and prev == "failed" and _cooldown_ok(key, "up", now_wall):
            up_events.append((server, check, outcome))

    await _send_down_events(bot, admin_ids, down_events, now_wall, heartbeat)

    for server, check, outcome in up_events:
        key = (server.composite_key, check.check_id)
        delivered = await send_check_up_notification(
            bot, admin_ids, server.name, _describe_check(check, server)
        )
        heartbeat()
        if delivered:
            _last_notified_check_status[key] = "ok"
            _last_check_notification_time[(key[0], key[1], "up")] = now_wall

    for server, check, outcome in ssl_events:
        key = (server.composite_key, check.check_id)
        invalid = outcome.status == CheckStatus.CERT_INVALID
        delivered = await send_ssl_expiry_notification(
            bot, admin_ids, server.name, _describe_check(check, server),
            days_left=outcome.days_until_expiry, invalid=invalid, detail=outcome.error,
        )
        heartbeat()
        if delivered:
            _last_ssl_alert_at[key] = now_wall


async def _send_down_events(
    bot: Bot,
    admin_ids: list[int],
    down_events: list[tuple[Server, CheckDefinition, CheckOutcome]],
    now_wall: float,
    heartbeat: Callable[[], None],
) -> None:
    """Send down alerts, rolling up into one message past the threshold.

    Args:
        bot: aiogram Bot.
        admin_ids: Administrator IDs.
        down_events: Newly-failing (server, check, outcome) triples (cooldown already checked).
        now_wall: Current wall-clock time.
        heartbeat: Progress callback, beaten after each send.

    Returns:
        None.
    """
    if not down_events:
        return

    if len(down_events) > ROLLUP_THRESHOLD:
        sample = [f"{s.name} — {_describe_check(c, s)}" for s, c, _ in down_events[:ROLLUP_THRESHOLD]]
        delivered = await send_checks_rollup_notification(
            bot, admin_ids, len(down_events), sample
        )
        heartbeat()
        if delivered:
            for server, check, _ in down_events:
                key = (server.composite_key, check.check_id)
                _last_notified_check_status[key] = "failed"
                _last_check_notification_time[(key[0], key[1], "down")] = now_wall
        return

    for server, check, outcome in down_events:
        key = (server.composite_key, check.check_id)
        delivered = await send_check_down_notification(
            bot, admin_ids, server.name, _describe_check(check, server), outcome.error
        )
        heartbeat()
        if delivered:
            _last_notified_check_status[key] = "failed"
            _last_check_notification_time[(key[0], key[1], "down")] = now_wall
