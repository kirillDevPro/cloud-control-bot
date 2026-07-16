"""ICMP-ping monitoring layer: per-server worker processes.

This package owns the ICMP side specifically — one worker process per server pinging on an
interval. Non-ICMP service checks (TCP/HTTP/SSL) live in ``src/checks`` and run in the main
process, not here. Re-exports the public API: PingManager (orchestrates per-server worker
processes) and ping_worker_function (the worker process entry point).
"""

from .ping_manager import PingManager
from .ping_worker import ping_worker_function

__all__ = ["PingManager", "ping_worker_function"]
