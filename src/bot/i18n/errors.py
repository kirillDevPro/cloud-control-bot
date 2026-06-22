"""Localize domain exceptions into per-recipient user-facing error text.

Provider/storage exceptions carry an English ``message`` that is always kept for
logs. When such an error must be SHOWN to a Telegram admin — an operation-failure
screen or a provider-outage/critical alert — the detail has to read in the
recipient's own language. This module maps each user-reachable exception type to
a catalog key plus parameters, so the same failure renders in EN / RU / UK.
Exceptions with no mapping fall back to their English ``str()`` (the full
technical text — HTTP codes, retry seconds, IAM hints — stays in the logs).

The mapping lives here, in the presentation layer, rather than on the exception
classes, so the domain stays free of catalog keys.
"""

from __future__ import annotations

from ... import exceptions as exc
from .translator import get_current_language, translate


def _error_descriptor(error: BaseException) -> tuple[str, dict[str, object]] | None:
    """Map an exception to its catalog key and template parameters.

    Args:
        error: The exception to localize.

    Returns:
        tuple[str, dict] | None: ``(catalog_key, params)`` for a known
        user-facing error, or None when there is no localized form and the caller
        should fall back to ``str(error)``.
    """
    match error:
        case exc.VultrAuthenticationError():
            return "error.invalid_token", {"provider": "Vultr"}
        case exc.HetznerAuthenticationError():
            return "error.invalid_token", {"provider": "Hetzner"}
        case exc.AWSAuthenticationError():
            return "error.invalid_token", {"provider": "AWS"}
        case exc.AWSPermissionError() | exc.VultrPermissionError() | exc.HetznerPermissionError():
            return "error.permission", {"operation": error.operation}
        case (
            exc.VultrNotFoundError()
            | exc.HetznerNotFoundError()
            | exc.AWSNotFoundError()
        ):
            return "error.not_found", {
                "resource_type": error.resource_type,
                "resource_id": error.resource_id,
            }
        case exc.VultrRateLimitError():
            return "error.rate_limit", {"provider": "Vultr"}
        case exc.HetznerRateLimitError():
            return "error.rate_limit", {"provider": "Hetzner"}
        case exc.AWSThrottlingError():
            return "error.rate_limit", {"provider": "AWS"}
        case exc.VultrServerError():
            return "error.server_side", {"provider": "Vultr"}
        case exc.HetznerServerError():
            return "error.server_side", {"provider": "Hetzner"}
        case exc.AWSServiceError():
            return "error.server_side", {"provider": "AWS"}
        case exc.HetznerConflictError():
            return "error.conflict", {
                "operation": error.operation,
                "state": error.server_status,
            }
        case exc.AWSInvalidStateError():
            return "error.conflict", {
                "operation": error.operation,
                "state": error.current_state,
            }
        case exc.HetznerLockedError():
            return "error.locked", {"resource_id": error.resource_id}
        # Base provider API errors wrap network / unexpected / unclassified
        # failures (e.g. AWSAPIError "Network error: ..."). They are user-reachable
        # via the sustained-outage and fetch-failed admin alerts, so map them to a
        # generic localized message instead of leaking the raw English string.
        # These MUST stay after every concrete subclass above — match is first-wins,
        # and each base class is a parent of the typed errors handled earlier.
        case exc.VultrAPIError():
            return "error.provider_api", {"provider": "Vultr"}
        case exc.HetznerAPIError():
            return "error.provider_api", {"provider": "Hetzner"}
        case exc.AWSAPIError():
            return "error.provider_api", {"provider": "AWS"}
        case _:
            return None


def translate_error(error: BaseException, language: str | None = None) -> str:
    """Render an exception's user-facing detail in an explicit recipient language.

    Args:
        error: The exception to localize.
        language: Target language; normalized/defaulted by :func:`translate`.

    Returns:
        str: The localized error text, or the English ``str(error)`` when the
        exception type has no localized form. The result is plain text; callers
        that interpolate it into an HTML message must escape it themselves.
    """
    descriptor = _error_descriptor(error)
    if descriptor is None:
        return str(error)
    key, params = descriptor
    return translate(key, language, **params)


def localize_error(error: BaseException) -> str:
    """Render an exception's user-facing detail in the active (context-var) language.

    Args:
        error: The exception to localize.

    Returns:
        str: The localized error text for the current language (``str(error)``
        fallback). Plain text — escape before interpolating into HTML.
    """
    return translate_error(error, get_current_language())
