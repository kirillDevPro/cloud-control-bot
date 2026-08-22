"""Shared helpers for inline keyboard builders."""

import math

from aiogram.types import InlineKeyboardButton

from ...models import Server
from ..utils.callback_data import encode_callback_data


def _paginate(servers: list[Server], page: int, per_page: int) -> tuple[list[Server], int, int]:
    """Paginate a server list and clamp stale page indexes.

    The page index is clamped into [0, total_pages-1] so a stale page (e.g. servers
    were removed since the keyboard was rendered) never yields a blank page with a
    misleading counter. Callers MUST use the returned page for the nav row/buttons.

    Args:
        servers: Full server list to paginate.
        page: Requested zero-based page index.
        per_page: Number of servers per page.

    Returns:
        Tuple of (servers on the current page, total number of pages, clamped page).
    """
    total_pages = math.ceil(len(servers) / per_page)
    # total_pages can be 0 when the list is empty; clamp keeps page at 0 then.
    page = max(0, min(page, total_pages - 1))
    start_idx = page * per_page
    return servers[start_idx : start_idx + per_page], total_pages, page


def _server_button_rows(
    page_servers: list[Server], encode_prefix: str
) -> list[list[InlineKeyboardButton]]:
    """Build one server button per row.

    Args:
        page_servers: Servers to render on the current page.
        encode_prefix: Callback prefix passed to encode_callback_data().

    Returns:
        Rows containing one status/name button per server.
    """
    rows: list[list[InlineKeyboardButton]] = []
    for server in page_servers:
        # Use only the status emoji (✅/❌), without a server icon
        status_emoji = server.status.to_emoji() if hasattr(server, "status") else "❓"
        button_text = f"{status_emoji} {server.name}"
        callback_data = encode_callback_data(encode_prefix, server.composite_key)
        rows.append([InlineKeyboardButton(text=button_text, callback_data=callback_data)])
    return rows


def _nav_row(
    page: int, total_pages: int, *, prev_cb: str, info_cb: str, next_cb: str
) -> list[InlineKeyboardButton] | None:
    """Build a pagination navigation row.

    Args:
        page: Current zero-based page index.
        total_pages: Total number of pages.
        prev_cb: Callback data for the previous-page button.
        info_cb: Callback data for the page indicator button.
        next_cb: Callback data for the next-page button.

    Returns:
        Navigation buttons, or None if there is only one page.
    """
    if total_pages <= 1:
        return None

    nav_buttons = [InlineKeyboardButton(text=f"📄 {page + 1}/{total_pages}", callback_data=info_cb)]
    if page > 0:
        nav_buttons.insert(0, InlineKeyboardButton(text="◀️", callback_data=prev_cb))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text="▶️", callback_data=next_cb))
    return nav_buttons
