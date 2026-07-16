"""Address validation chokepoint for service checks.

Every TCP/HTTP/SSL check MUST resolve its target through :func:`resolve_target` before
connecting. This is the central static guard against the feature's worst failure mode: providers
substitute ``0.0.0.0`` as a sentinel when a server has no public IP (see
``providers/hetzner.py`` and ``providers/vultr.py``) and leave the server enabled. On
Linux a TCP connect to ``0.0.0.0`` reaches localhost, so a naive check would report a dead
server HEALTHY — a false positive strictly worse than ICMP's honest false negative. The
same door is open on the user-typed HTTP URL host (``http://127.0.0.1/``), so URL hosts run
through here too. Hostnames are screened by name but resolved later by the network client.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass


@dataclass(frozen=True)
class ResolvedTarget:
    """A validated, connect-safe check target.

    Attributes:
        host: The address/hostname to connect to (a bare IP or a hostname; NOT bracketed —
            use :func:`format_host_port` for display).
        is_private: True when the host is an RFC1918/ULA private address. Private targets
            are ALLOWED (a co-located bot can legitimately check a private server) but the
            caller logs the fact once so an unexpected private target is visible.
    """

    host: str
    is_private: bool


def resolve_target(host: str) -> ResolvedTarget | None:
    """Validate a check target host, rejecting addresses that would give a false positive.

    Rejects (returns ``None``): the ``0.0.0.0``/``::`` unspecified sentinel, loopback,
    link-local, multicast, and otherwise-reserved IP literals, plus the ``localhost``
    hostname family. A real IP or hostname is accepted; private IPs are accepted with the
    ``is_private`` flag set.

    Hostnames are not DNS-resolved here (that would block the event loop and belongs at
    connect time); only the obvious ``localhost`` footgun is rejected by name.

    Args:
        host: The target host — a bare IP literal or a hostname (e.g. from a URL).

    Returns:
        ResolvedTarget | None: The validated target, or None when the host must not be
            connected to.
    """
    if not host or not host.strip():
        return None
    # Strip a trailing dot (the DNS root form) BEFORE any check: "127.0.0.1." and
    # "localhost." otherwise fail IP parsing and the name check, falling through as accepted
    # hostnames that resolve straight back to a forbidden loopback/unspecified address.
    candidate = host.strip().rstrip(".")
    if not candidate:
        return None

    # Reject the localhost hostname family by name (no DNS needed).
    lowered = candidate.lower()
    if lowered == "localhost" or lowered.endswith(".localhost"):
        return None

    try:
        addr = ipaddress.ip_address(candidate)
    except ValueError:
        # Not an IP literal -> treat as a hostname. Accepted (resolved at connect time);
        # not private by this static check.
        return ResolvedTarget(host=candidate, is_private=False)

    # An IP literal: reject every address family that would be a false positive or unsafe.
    if (
        addr.is_unspecified  # 0.0.0.0 / :: -> localhost on connect (the core landmine)
        or addr.is_loopback  # 127.0.0.0/8, ::1
        or addr.is_link_local  # 169.254/16, fe80::/10
        or addr.is_multicast
        or addr.is_reserved
    ):
        return None

    return ResolvedTarget(host=str(addr), is_private=addr.is_private)


def _is_ipv6_literal(host: str) -> bool:
    """Return whether the host is an IPv6 address literal (needs bracketing in host:port).

    Args:
        host: A host string (IP literal or hostname).

    Returns:
        bool: True only when host parses as an IPv6 address.
    """
    try:
        return ipaddress.ip_address(host).version == 6
    except ValueError:
        return False


def format_host_port(host: str, port: int) -> str:
    """Format a host and port for display, bracketing an IPv6 literal.

    ``f"{host}:{port}"`` is wrong for an IPv6 literal (``2a01::1:443`` is ambiguous); it
    must be ``[2a01::1]:443``. Used for logs and the check-detail screen, never for the
    actual connect (``asyncio.open_connection`` takes host and port separately).

    Args:
        host: The target host.
        port: The target port.

    Returns:
        str: ``host:port`` for IPv4/hostnames, ``[host]:port`` for IPv6 literals.
    """
    if _is_ipv6_literal(host):
        return f"[{host}]:{port}"
    return f"{host}:{port}"
