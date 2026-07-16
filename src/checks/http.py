"""HTTP(S) endpoint check using the shared httpx.AsyncClient (no new dependency)."""

from __future__ import annotations

import asyncio
import time

import httpx

from .outcome import CheckOutcome
from .target import resolve_target
from ..models.service_check import CheckStatus

# Cap the body read for the keyword match. client.get() would buffer the WHOLE body before
# a slice could bound it, so the check streams and stops at this many bytes — a large or
# endless response can never exhaust memory.
_MAX_BODY_BYTES = 64 * 1024

# Redirects are followed MANUALLY (never httpx follow_redirects=True) so every hop's host is
# re-validated through the address chokepoint: automatic redirects would let a safe-looking
# endpoint bounce to 0.0.0.0/127.0.0.1/link-local and turn a dead service green. Bounded so a
# redirect loop cannot spin forever.
_MAX_REDIRECTS = 5

# HTTP redirect status codes that carry a Location to follow.
_REDIRECT_CODES = frozenset({301, 302, 303, 307, 308})


async def check_http_endpoint(
    client: httpx.AsyncClient,
    url: str,
    *,
    expected_status: int | None,
    keyword: str | None,
    timeout: float,
) -> CheckOutcome:
    """Check an HTTP(S) endpoint's status, optional body keyword, and latency.

    The URL host is validated through resolve_target FIRST, and so is EVERY redirect target
    (redirects are followed manually, not by httpx): a user-typed ``http://0.0.0.0/`` or a
    redirect to ``http://127.0.0.1/`` is the same false-positive door the address chokepoint
    closes for TCP/SSL, so it is closed here too. The whole request-and-body scan runs under a
    hard wall-clock deadline, because httpx's timeout only bounds per-operation inactivity — a
    peer dripping bytes under that threshold could otherwise stall the check indefinitely.

    Args:
        client: The shared httpx.AsyncClient (never constructed here).
        url: The full target URL.
        expected_status: Required status code; defaults to 200 when None.
        keyword: Optional substring that must appear in the (bounded) response body.
        timeout: Per-request AND total wall-clock timeout in seconds.

    Returns:
        CheckOutcome: OK on a passing request; ASSERT_FAILED on a wrong status or a missing
            keyword (reachable but wrong); TIMEOUT on timeout; FAILED on an invalid/unsafe
            URL, an unsafe redirect target, too many redirects, or a transport error.
    """
    # Validate the URL and its host before making any request.
    try:
        parsed = httpx.URL(url)
    except (httpx.InvalidURL, TypeError, ValueError):
        return CheckOutcome(status=CheckStatus.FAILED, error="Invalid URL")
    host = parsed.host
    if not host:
        return CheckOutcome(status=CheckStatus.FAILED, error="URL has no host")
    if resolve_target(host) is None:
        return CheckOutcome(status=CheckStatus.FAILED, error=f"Unsafe target host: {host}")

    want_status = expected_status if expected_status is not None else 200
    start = time.monotonic()
    try:
        async with asyncio.timeout(timeout):
            return await _request_following_redirects(client, parsed, want_status, keyword, timeout, start)
    except (TimeoutError, httpx.TimeoutException):
        return CheckOutcome(status=CheckStatus.TIMEOUT, error=f"Request timed out after {timeout}s")
    except (httpx.HTTPError, OSError) as exc:
        return CheckOutcome(status=CheckStatus.FAILED, error=f"Request failed: {exc}")


async def _request_following_redirects(
    client: httpx.AsyncClient,
    url: httpx.URL,
    want_status: int,
    keyword: str | None,
    timeout: float,
    start: float,
) -> CheckOutcome:
    """Issue the GET, following redirects manually with each hop's host re-validated.

    Args:
        client: The shared httpx client.
        url: The (already validated) target URL.
        want_status: The status code the final response must have.
        keyword: Optional required response-body substring.
        timeout: Per-operation httpx timeout in seconds.
        start: monotonic() at the start of the whole check, for latency.

    Returns:
        CheckOutcome: The check result for the final (non-redirect) response, or a FAILED
            outcome on an unsafe/absent redirect target or too many hops.
    """
    current = url
    for _hop in range(_MAX_REDIRECTS + 1):
        async with client.stream(
            "GET", current, timeout=httpx.Timeout(timeout), follow_redirects=False
        ) as response:
            latency_ms = (time.monotonic() - start) * 1000.0

            if response.status_code in _REDIRECT_CODES:
                location = response.headers.get("location")
                if not location:
                    return CheckOutcome(status=CheckStatus.FAILED, error="Redirect without a Location")
                nxt = current.join(location)
                next_host = nxt.host
                if not next_host or resolve_target(next_host) is None:
                    return CheckOutcome(
                        status=CheckStatus.FAILED,
                        error=f"Unsafe redirect target: {next_host or '?'}",
                    )
                current = nxt
                continue

            if response.status_code != want_status:
                return CheckOutcome(
                    status=CheckStatus.ASSERT_FAILED,
                    latency_ms=latency_ms,
                    error=f"Status {response.status_code}, expected {want_status}",
                )

            if keyword:
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body += chunk
                    if len(body) >= _MAX_BODY_BYTES:
                        break
                text = bytes(body[:_MAX_BODY_BYTES]).decode("utf-8", errors="replace")
                if keyword not in text:
                    return CheckOutcome(
                        status=CheckStatus.ASSERT_FAILED,
                        latency_ms=latency_ms,
                        error="Keyword not found in response body",
                    )

            return CheckOutcome(status=CheckStatus.OK, latency_ms=latency_ms)

    return CheckOutcome(status=CheckStatus.FAILED, error=f"Too many redirects (>{_MAX_REDIRECTS})")
