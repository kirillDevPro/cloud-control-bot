"""The runner-to-task transport type.

A check runner knows HOW to probe (connect, request, handshake) but nothing about server
identity. It returns a :class:`CheckOutcome`; the ``service_checks_task`` stamps the
identity (server_id / provider_alias / check_id) onto it to build a persisted
``ServiceCheckResult``. This seam is what lets the runners be tested without a server.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..models.service_check import CheckStatus


@dataclass(frozen=True)
class CheckOutcome:
    """The identity-free result of running one check.

    Attributes:
        status: The check outcome.
        latency_ms: Measured connect/response latency in ms, when applicable.
        error: Short error detail for a failed run (English; escaped by the UI layer).
        days_until_expiry: Days until certificate expiry (SSL only; negative when expired).
        not_after: Certificate notAfter timestamp (SSL only).
    """

    status: CheckStatus
    latency_ms: float | None = None
    error: str | None = None
    days_until_expiry: int | None = None
    not_after: datetime | None = None
