"""Convenience exports for Telegram bot utility helpers.

The screen helpers expose both reply-message navigation and callback-driven
screen replacement so routers can keep one clean live bot screen per chat.
"""

from .message_editor import safe_edit_message
from .error_handler import handle_telegram_errors
from .callback_data import encode_callback_data, decode_callback_data
from .server_state import apply_shared_status
from .screen import reset_screen_from_callback, show_screen
from .server_lookup import parse_server_key, resolve_server
from .rich import answer_rich, edit_rich, send_rich

__all__ = [
    "safe_edit_message",
    "handle_telegram_errors",
    "encode_callback_data",
    "decode_callback_data",
    "apply_shared_status",
    "show_screen",
    "reset_screen_from_callback",
    "parse_server_key",
    "resolve_server",
    "answer_rich",
    "edit_rich",
    "send_rich",
]
