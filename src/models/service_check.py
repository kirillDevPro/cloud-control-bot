"""Service-check models: per-server TCP/HTTP/SSL check definitions and their results.

These sit alongside the ICMP ping models but are deliberately separate: service checks
run in the main process (not the ping workers), are configured per server from chat, and
never touch the ping IPC queue or the ping-stats tables. New fields use ``provider_alias``
rather than the legacy ``provider_type`` name, which on the ping side actually carries an
alias — a misnomer not worth copying into greenfield models.
"""

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


class CheckType(str, Enum):
    """Kind of service check. Inherits from str so it serializes to JSON cleanly."""

    TCP = "tcp"
    HTTP = "http"
    SSL = "ssl"

    def __str__(self) -> str:
        """Return the underlying string value of the check type.

        Returns:
            str: The serialized check-type value.
        """
        return self.value


# Display emoji per check type, shared by the check-list keyboard and the detail formatter.
# (The ASCII-only rule is for logs/provider output; real emoji are fine in UI strings.)
CHECK_TYPE_EMOJI: dict[CheckType, str] = {
    CheckType.TCP: "🔌",
    CheckType.HTTP: "🌐",
    CheckType.SSL: "🔒",
}


class CheckStatus(str, Enum):
    """Outcome of a single service-check run.

    ``ASSERT_FAILED`` distinguishes "reachable but wrong content/status" from ``FAILED``
    ("unreachable"). ``CERT_EXPIRING`` / ``CERT_INVALID`` are SSL-specific: the cert was
    read but is close to expiry, or it is expired or its certificate chain did not verify.
    Hostname identity is not checked because SSL service checks target server IPs.
    """

    OK = "ok"
    FAILED = "failed"
    TIMEOUT = "timeout"
    ASSERT_FAILED = "assert_failed"
    CERT_EXPIRING = "cert_expiring"
    CERT_INVALID = "cert_invalid"

    def __str__(self) -> str:
        """Return the underlying string value of the status.

        Returns:
            str: The serialized check-status value.
        """
        return self.value


def _generate_check_id() -> str:
    """Return a short unique identifier for a check definition.

    Returns:
        str: The first 8 hex chars of a uuid4 — short enough for compact callback_data,
            wide enough that per-server collisions are not a practical concern.
    """
    return uuid4().hex[:8]


class CheckDefinition(BaseModel):
    """One user-configured service check for a server.

    Cadence and timeouts are NOT stored here — they come from the global Settings knobs
    (``SERVICE_CHECK_INTERVAL`` / ``SSL_CHECK_INTERVAL`` / ``TCP_CHECK_TIMEOUT`` /
    ``HTTP_CHECK_TIMEOUT``) so a chat value can never silently diverge from a deployment
    knob. ``warn_days`` is the one exception: an OPTIONAL per-check override of the global
    ``SSL_EXPIRY_WARN_DAYS`` (``None`` means "use the global"), a genuine product need — a
    critical service warrants a wider warning window than a minor one.
    """

    check_id: str = Field(default_factory=_generate_check_id, description="Unique check ID")

    type: CheckType = Field(..., description="Kind of check (tcp/http/ssl)")

    enabled: bool = Field(default=True, description="Whether this check runs")

    # TCP / SSL target port (SSL defaults to 443 when unset; TCP requires it).
    port: int | None = Field(default=None, description="Target port (TCP/SSL)", ge=1, le=65535)

    # HTTP target URL (full http(s):// URL, host validated at run time via resolve_target).
    url: str | None = Field(default=None, description="Target URL (HTTP)")

    # Optional HTTP response-body substring that must be present for the check to pass.
    keyword: str | None = Field(default=None, description="Required response-body substring (HTTP)")

    # Optional HTTP status assertion (defaults to 200 at run time when unset).
    expected_status: int | None = Field(
        default=None, description="Expected HTTP status code", ge=100, le=599
    )

    # Optional per-check override of the global SSL warn-days threshold.
    warn_days: int | None = Field(
        default=None, description="Per-check SSL expiry warning window in days", ge=1, le=365
    )

    @field_validator("port", "expected_status", "warn_days", mode="before")
    @classmethod
    def _reject_bool(cls, v: Any) -> Any:
        """Reject a bool for the integer fields.

        ``bool`` is a subclass of ``int``, so ``True``/``False`` from a hand-edited JSON
        file would otherwise coerce to 1/0 and silently mean a wrong port or threshold.

        Args:
            v: The candidate value for the field.

        Returns:
            Any: The value unchanged when it is not a bool.

        Raises:
            ValueError: If the value is a bool.
        """
        if isinstance(v, bool):
            raise ValueError("must be an integer, not a bool")
        return v

    @property
    def effective_port(self) -> int:
        """Return the port to probe: the configured port, else 443 for SSL, else 0.

        Centralizes the "SSL defaults to 443" rule so the runner and the UI labels never
        disagree on it.

        Returns:
            int: The configured ``port`` when set; otherwise 443 for an SSL check (the
                default HTTPS port) or 0 for any other type left without a port.
        """
        if self.port is not None:
            return self.port
        return 443 if self.type == CheckType.SSL else 0


class ServiceCheckResult(BaseModel):
    """Result of a single service-check run, published directly to stats and alerts.

    This is its own model, NOT a widened ``PingResult``: it never rides the ping IPC queue.
    """

    server_id: str = Field(..., description="Server ID")

    provider_alias: str = Field(..., description="Provider alias scoping the server")

    check_id: str = Field(..., description="ID of the check that produced this result")

    type: CheckType = Field(..., description="Kind of check (tcp/http/ssl)")

    timestamp: datetime = Field(default_factory=datetime.now, description="Run time")

    status: CheckStatus = Field(..., description="Outcome of the run")

    latency_ms: float | None = Field(
        default=None, description="Connect/response latency in ms (when measured)", ge=0.0
    )

    error: str | None = Field(default=None, description="Error detail for a failed run")

    # SSL-specific: days until the certificate expires (negative when already expired).
    days_until_expiry: int | None = Field(
        default=None, description="Days until certificate expiry (SSL)"
    )

    not_after: datetime | None = Field(
        default=None, description="Certificate notAfter timestamp (SSL)"
    )

    def is_ok(self) -> bool:
        """Return whether this run counts as healthy.

        Returns:
            bool: True only for a fully passing ``OK`` run. ``CERT_EXPIRING`` remains a
                certificate warning even though the endpoint is reachable.
        """
        return self.status == CheckStatus.OK
