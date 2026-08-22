"""Inline keyboard builders for monitoring and server controls."""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from ...models import Server
from ..i18n import _
from ..utils.callback_data import encode_callback_data
from .inline_common import _nav_row, _paginate, _server_button_rows


def get_monitoring_keyboard(
    servers: list[Server], page: int = 0, per_page: int = 8
) -> InlineKeyboardMarkup:
    """
    Return an inline keyboard with a paginated list of servers.

    Args:
        servers: List of servers to display.
        page: Current page number (zero-based).
        per_page: Number of servers per page.

    Returns:
        InlineKeyboardMarkup: Keyboard with the server list.
    """
    page_servers, total_pages, page = _paginate(servers, page, per_page)

    keyboard = _server_button_rows(page_servers, "monitor_details_")

    nav_row = _nav_row(
        page,
        total_pages,
        prev_cb=f"monitor_page_{page - 1}",
        info_cb="monitor_page_info",
        next_cb=f"monitor_page_{page + 1}",
    )
    if nav_row:
        keyboard.append(nav_row)

    # "Refresh" button
    keyboard.append(
        [InlineKeyboardButton(text=_("common.refresh"), callback_data=f"monitor_refresh_{page}")]
    )

    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_server_details_keyboard(server_key: str) -> InlineKeyboardMarkup:
    """
    Return an inline keyboard for the server detail view.

    Args:
        server_key: Composite server key in the format "provider:server_id".

    Returns:
        InlineKeyboardMarkup: Keyboard with the server action buttons.
    """
    keyboard = [
        [
            InlineKeyboardButton(
                text=_("kb.statistics"),
                callback_data=encode_callback_data("monitor_stats_", server_key),
            )
        ],
        [
            InlineKeyboardButton(
                text=_("kb.manage"),
                callback_data=encode_callback_data("server_control_", server_key),
            )
        ],
        [InlineKeyboardButton(text=_("common.back"), callback_data="monitor_back")],
    ]

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_server_stats_keyboard(server_key: str) -> InlineKeyboardMarkup:
    """
    Return an inline keyboard for the statistics view.

    Args:
        server_key: Composite server key in the format "provider:server_id".

    Returns:
        InlineKeyboardMarkup: Keyboard with the statistics action buttons.
    """
    keyboard = [
        [
            InlineKeyboardButton(
                text=_("common.refresh"),
                callback_data=encode_callback_data("monitor_stats_", server_key),
            )
        ],
        [
            InlineKeyboardButton(
                text=_("common.back"),
                callback_data=encode_callback_data("monitor_details_", server_key),
            )
        ],
    ]

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_servers_management_keyboard(
    servers: list[Server], page: int = 0, per_page: int = 8, provider: str | None = None
) -> InlineKeyboardMarkup:
    """
    Return an inline keyboard with a paginated list of servers for management.

    Args:
        servers: List of servers to display.
        page: Current page number (zero-based).
        per_page: Number of servers per page.
        provider: Provider alias (used in navigation callback_data).

    Returns:
        InlineKeyboardMarkup: Keyboard with the server list.
    """
    page_servers, total_pages, page = _paginate(servers, page, per_page)

    keyboard = _server_button_rows(page_servers, "server_control_")

    # An alias may contain "_", so the navigation callbacks are built with the provider in mind
    nav_row = _nav_row(
        page,
        total_pages,
        prev_cb=f"servers_page_{provider}_{page - 1}" if provider else f"servers_page_{page - 1}",
        info_cb="servers_page_info",
        next_cb=f"servers_page_{provider}_{page + 1}" if provider else f"servers_page_{page + 1}",
    )
    if nav_row:
        keyboard.append(nav_row)

    # Action buttons (Back to providers + Refresh)
    action_buttons = []

    # "Back to providers" button (only when a provider is selected)
    if provider:
        action_buttons.append(
            InlineKeyboardButton(text=_("kb.back_to_providers"), callback_data="servers_back")
        )

    # "Refresh" button
    refresh_data = f"servers_refresh_{provider}_{page}" if provider else f"servers_refresh_{page}"
    action_buttons.append(InlineKeyboardButton(text=_("common.refresh"), callback_data=refresh_data))

    keyboard.append(action_buttons)

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_server_control_keyboard(
    server_key: str,
    power_status: str | None = None,
    supports_graceful: bool = False,
    check_count: int = 0,
) -> InlineKeyboardMarkup:
    """
    Return an inline keyboard for managing a server.

    Buttons are rendered dynamically depending on power_status in a 2x2 + Back layout:
    - "running": [Restart | Stop] / [Refresh] / [Back]
    - "stopped": [Start] / [Refresh] / [Back]
    - "pending" or None: [Start | Stop] / [Restart | Refresh] / [Back]

    If supports_graceful=True and the server is not stopped, a separate row with a
    graceful shutdown (ACPI) button is added before the "Back" button. A "Checks (N)" row
    (N = the count of configured service checks) is added before "Back".

    Args:
        server_key: Composite server key in the format "provider:server_id".
        power_status: Server status from the provider API ("running", "stopped", "pending").
        supports_graceful: Whether the provider supports graceful shutdown (ACPI).
        check_count: Number of configured service checks (shown on the Checks button).

    Returns:
        InlineKeyboardMarkup: Keyboard with the management buttons.
    """
    keyboard = []

    # Decide which operations are available based on the status
    if power_status == "running":
        # Server is running - row 1: [Restart | Stop]
        keyboard.append(
            [
                InlineKeyboardButton(
                    text=_("kb.restart"),
                    callback_data=encode_callback_data("server_reboot_", server_key),
                ),
                InlineKeyboardButton(
                    text=_("kb.stop"),
                    callback_data=encode_callback_data("server_stop_", server_key),
                ),
            ]
        )
        # Row 2: [Refresh]
        keyboard.append(
            [
                InlineKeyboardButton(
                    text=_("common.refresh"),
                    callback_data=encode_callback_data("server_refresh_", server_key),
                )
            ]
        )
    elif power_status == "stopped":
        # Server is stopped - row 1: [Start]
        keyboard.append(
            [
                InlineKeyboardButton(
                    text=_("kb.start"),
                    callback_data=encode_callback_data("server_start_", server_key),
                )
            ]
        )
        # Row 2: [Refresh]
        keyboard.append(
            [
                InlineKeyboardButton(
                    text=_("common.refresh"),
                    callback_data=encode_callback_data("server_refresh_", server_key),
                )
            ]
        )
    else:
        # Unknown status or pending - row 1: [Start | Stop]
        keyboard.append(
            [
                InlineKeyboardButton(
                    text=_("kb.start"),
                    callback_data=encode_callback_data("server_start_", server_key),
                ),
                InlineKeyboardButton(
                    text=_("kb.stop"),
                    callback_data=encode_callback_data("server_stop_", server_key),
                ),
            ]
        )
        # Row 2: [Restart | Refresh]
        keyboard.append(
            [
                InlineKeyboardButton(
                    text=_("kb.restart"),
                    callback_data=encode_callback_data("server_reboot_", server_key),
                ),
                InlineKeyboardButton(
                    text=_("common.refresh"),
                    callback_data=encode_callback_data("server_refresh_", server_key),
                ),
            ]
        )

    # Graceful shutdown — a separate row (only when the provider supports it
    # and the server is not stopped; the operation is meaningless for a stopped server)
    if supports_graceful and power_status != "stopped":
        keyboard.append(
            [
                InlineKeyboardButton(
                    text=_("kb.shutdown_acpi"),
                    callback_data=encode_callback_data("server_shutdown_", server_key),
                )
            ]
        )

    # Service checks row (TCP/HTTP/SSL) — its own sub-screen.
    keyboard.append(
        [
            InlineKeyboardButton(
                text=_("checks.button", count=check_count),
                callback_data=encode_callback_data("chk_list_", server_key),
            )
        ]
    )

    # [Back] row
    keyboard.append([InlineKeyboardButton(text=_("common.back"), callback_data="servers_back")])

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_confirmation_keyboard(action: str, server_key: str) -> InlineKeyboardMarkup:
    """
    Return an inline keyboard for confirming a critical operation.

    Args:
        action: Operation type ("stop", "reboot", or "shutdown").
        server_key: Composite server key in the format "provider:server_id".

    Returns:
        InlineKeyboardMarkup: Keyboard with the confirmation buttons.
    """
    keyboard = [
        [
            InlineKeyboardButton(
                text=_("kb.confirm"),
                callback_data=encode_callback_data(f"server_confirm_{action}_", server_key),
            )
        ],
        [
            InlineKeyboardButton(
                text=_("kb.cancel"),
                callback_data=encode_callback_data(f"server_cancel_{action}_", server_key),
            )
        ],
    ]

    return InlineKeyboardMarkup(inline_keyboard=keyboard)
