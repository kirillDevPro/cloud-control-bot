"""SSL/TLS certificate expiry check via a dual handshake.

Reading an EXPIRED or otherwise-invalid certificate is the whole point of this check, and
``getpeercert()``'s parsed-dict form returns nothing unless verification SUCCEEDED. So the
first handshake disables verification (``CERT_NONE``) purely to obtain the DER bytes, which
``cryptography`` parses for the tz-aware ``not_valid_after_utc``. A second, verifying
    handshake then runs only to surface certificate-chain/trust problems as ``CERT_INVALID``;
    hostname matching is deliberately disabled because service checks target server IPs. Its
failure never hides the expiry the first handshake already read.
"""

from __future__ import annotations

import asyncio
import ssl
import time
from datetime import datetime, timezone

from cryptography import x509

from .outcome import CheckOutcome
from ..models.service_check import CheckStatus


async def _close(writer: asyncio.StreamWriter | None) -> None:
    """Close a stream writer, swallowing a close-time transport error.

    Args:
        writer: The writer to close, or None.

    Returns:
        None.
    """
    if writer is None:
        return
    writer.close()
    try:
        await writer.wait_closed()
    except (OSError, ssl.SSLError):
        pass


async def check_ssl_expiry(
    host: str, port: int, warn_days: int, timeout: float
) -> CheckOutcome:
    """Check a TLS endpoint's certificate expiry and validity.

    Args:
        host: Target host (already validated via resolve_target).
        port: Target TLS port (typically 443).
        warn_days: Start warning when the certificate expires within this many days.
        timeout: Per-handshake timeout in seconds.

    Returns:
        CheckOutcome: CERT_INVALID when the certificate is expired or fails verification;
            CERT_EXPIRING when it is valid but within the warning window; OK when valid and
            beyond it; TIMEOUT/FAILED when the certificate could not be obtained at all.
            ``days_until_expiry`` and ``not_after`` are populated whenever the cert was read.
    """
    # --- Pass 1: obtain the certificate even if it is expired or self-signed. ---
    # CERT_NONE is deliberate and safe here: this handshake transfers NO data — it reads
    # the peer certificate and closes. Verification is not skipped for the check's verdict;
    # it is performed by the separate verifying handshake in _verify_certificate (pass 2).
    # Disabling verification is the ONLY way to read an expired/invalid cert's fields, which
    # is the entire purpose of an expiry check (getpeercert returns nothing otherwise).
    unverified_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    unverified_ctx.check_hostname = False
    unverified_ctx.verify_mode = ssl.CERT_NONE

    start = time.monotonic()
    writer: asyncio.StreamWriter | None = None
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port, ssl=unverified_ctx, server_hostname=host),
            timeout=timeout,
        )
        latency_ms = (time.monotonic() - start) * 1000.0
        ssl_object = writer.get_extra_info("ssl_object")
        der = ssl_object.getpeercert(binary_form=True) if ssl_object is not None else None
    except asyncio.TimeoutError:
        return CheckOutcome(status=CheckStatus.TIMEOUT, error=f"TLS handshake timed out after {timeout}s")
    except ssl.SSLError as exc:
        return CheckOutcome(status=CheckStatus.FAILED, error=f"TLS handshake failed: {exc}")
    except (ConnectionRefusedError, OSError) as exc:
        return CheckOutcome(status=CheckStatus.FAILED, error=f"Connect failed: {exc}")
    finally:
        await _close(writer)

    if not der:
        return CheckOutcome(status=CheckStatus.FAILED, error="No certificate presented")

    try:
        cert = x509.load_der_x509_certificate(der)
        not_after = cert.not_valid_after_utc
    except (ValueError, TypeError) as exc:
        return CheckOutcome(status=CheckStatus.FAILED, error=f"Unparseable certificate: {exc}")

    days_until_expiry = (not_after - datetime.now(timezone.utc)).days
    error: str | None = None

    if days_until_expiry < 0:
        # Already expired -> CERT_INVALID regardless of chain/trust; skip the second
        # (verifying) handshake entirely so an expired endpoint costs one handshake, not two.
        status = CheckStatus.CERT_INVALID
        error = f"Certificate expired {abs(days_until_expiry)}d ago"
    else:
        # --- Pass 2: verify the trust chain, to classify an unexpired-but-untrusted cert. ---
        verify_error = await _verify_certificate(host, port, timeout)
        if verify_error is not None:
            status = CheckStatus.CERT_INVALID
            error = verify_error
        elif days_until_expiry <= warn_days:
            status = CheckStatus.CERT_EXPIRING
        else:
            status = CheckStatus.OK

    return CheckOutcome(
        status=status,
        latency_ms=latency_ms,
        error=error,
        days_until_expiry=days_until_expiry,
        not_after=not_after,
    )


async def _verify_certificate(host: str, port: int, timeout: float) -> str | None:
    """Run a verifying handshake and return a description of any chain/trust failure.

    Verifies the certificate CHAIN and trust (``CERT_REQUIRED`` via the default context) but
    NOT the hostname identity: a check targets a server by IP, so there is no hostname to
    match, and matching the presented cert's names against an IP literal would flag every
    ordinary domain certificate as invalid. Expiry (the primary signal) comes from pass 1
    regardless; this pass only classifies an untrusted/self-signed chain as ``CERT_INVALID``.

    A transport-level failure here (timeout, refused) returns None: the endpoint was
    already reachable in pass 1, so a transient pass-2 failure must NOT be reported as an
    invalid certificate — only an actual verification failure is.

    Args:
        host: Target host.
        port: Target TLS port.
        timeout: Handshake timeout in seconds.

    Returns:
        str | None: A short description of the verification failure, or None when the
            certificate's chain verified or could not be re-checked transiently.
    """
    verify_ctx = ssl.create_default_context()
    # Verify the trust chain but not the hostname: the target is an IP, so hostname identity
    # matching is meaningless here and would false-flag valid domain certs as CERT_INVALID.
    verify_ctx.check_hostname = False
    writer: asyncio.StreamWriter | None = None
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port, ssl=verify_ctx, server_hostname=host),
            timeout=timeout,
        )
        return None
    except ssl.SSLCertVerificationError as exc:
        return f"Certificate verification failed: {exc.verify_message or exc}"
    except ssl.SSLError as exc:
        return f"TLS verification error: {exc}"
    except (asyncio.TimeoutError, ConnectionRefusedError, OSError):
        # Transient/transport failure on the verify pass; expiry from pass 1 still stands.
        return None
    finally:
        await _close(writer)
