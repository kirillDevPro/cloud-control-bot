"""Message formatting package for the Telegram bot."""

from .common import format_number, format_days_as_period
from .servers import (
    format_provider_selection,
    format_servers_management_list,
    format_server_control_details,
    format_confirmation_message,
    format_operation_result,
)
from .monitoring import (
    format_monitoring_dashboard,
    format_servers_list,
    format_server_details,
    format_statistics,
)
from .balance import (
    collect_provider_balances,
    format_balance_main,
    format_balance_history,
    format_balance_provider_detail,
)

__all__ = [
    # common
    "format_number",
    "format_days_as_period",
    # servers
    "format_provider_selection",
    "format_servers_management_list",
    "format_server_control_details",
    "format_confirmation_message",
    "format_operation_result",
    # monitoring
    "format_monitoring_dashboard",
    "format_servers_list",
    "format_server_details",
    "format_statistics",
    # balance
    "collect_provider_balances",
    "format_balance_main",
    "format_balance_history",
    "format_balance_provider_detail",
]
