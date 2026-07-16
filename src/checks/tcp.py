"""TCP port reachability check (stdlib asyncio, no dependency)."""

from __future__ import annotations

import asyncio
import time

from .outcome import CheckOutcome
from ..models.service_check import CheckStatus


async def check_tcp_port(host: str, port: int, timeout: float) -> CheckOutcome:
    """Check whether a TCP port accepts a connection, measuring connect latency.

    Opens a connection and immediately closes it — success means the port is open and
    something is listening. The connection is always closed in a finally so a half-open
    socket never leaks.

    Args:
        host: Target host (already validated via resolve_target).
        port: Target TCP port.
        timeout: Connect timeout in seconds.

    Returns:
        CheckOutcome: OK with latency on connect; FAILED on refusal/unreachable; TIMEOUT
            when the connect exceeds the timeout.
    """
    start = time.monotonic()
    writer: asyncio.StreamWriter | None = None
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
        latency_ms = (time.monotonic() - start) * 1000.0
        return CheckOutcome(status=CheckStatus.OK, latency_ms=latency_ms)
    except asyncio.TimeoutError:
        return CheckOutcome(status=CheckStatus.TIMEOUT, error=f"Connect timed out after {timeout}s")
    except ConnectionRefusedError:
        return CheckOutcome(status=CheckStatus.FAILED, error="Connection refused")
    except OSError as exc:
        return CheckOutcome(status=CheckStatus.FAILED, error=f"Connect failed: {exc}")
    finally:
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                # The peer may have already dropped the half-open socket; the check
                # result is already decided, so a close-time error is not actionable.
                pass
