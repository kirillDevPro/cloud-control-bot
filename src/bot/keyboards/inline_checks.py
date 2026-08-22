"""Inline keyboard builders for service checks."""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from ...models.service_check import CHECK_TYPE_EMOJI, CheckDefinition, CheckType
from ..i18n import _
from ..utils.callback_data import encode_callback_data


def _check_button_label(check: CheckDefinition) -> str:
    """Build a compact list-button label for a check (emoji + type + short target).

    Args:
        check: The check definition.

    Returns:
        str: e.g. "🔌 TCP :443", "🌐 HTTP /health", "🔒 SSL :443". Disabled checks are
            prefixed with a muted marker.
    """
    emoji = CHECK_TYPE_EMOJI.get(check.type, "•")
    if check.type == CheckType.HTTP:
        target = check.url or "?"
        if len(target) > 30:
            target = target[:29] + "…"
    else:
        target = f":{check.effective_port}"
    prefix = "" if check.enabled else "⏸ "
    return f"{prefix}{emoji} {check.type.value.upper()} {target}"


def get_checks_list_keyboard(
    server_key: str, checks: list[CheckDefinition]
) -> InlineKeyboardMarkup:
    """Return the keyboard for a server's service-check list.

    One button per check (opens its detail), an Add button, and Back to server control.

    Args:
        server_key: Composite server key.
        checks: The server's configured checks.

    Returns:
        InlineKeyboardMarkup: The checks-list keyboard.
    """
    keyboard = [
        [
            InlineKeyboardButton(
                text=_check_button_label(check),
                callback_data=encode_callback_data("chk_show_", f"{server_key}|{check.check_id}"),
            )
        ]
        for check in checks
    ]
    keyboard.append(
        [
            InlineKeyboardButton(
                text=_("checks.kb.add"),
                callback_data=encode_callback_data("chk_add_", server_key),
            )
        ]
    )
    keyboard.append(
        [
            InlineKeyboardButton(
                text=_("common.back"),
                callback_data=encode_callback_data("chk_back_", server_key),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_check_type_keyboard(server_key: str) -> InlineKeyboardMarkup:
    """Return the keyboard to choose a new check's type (TCP / HTTP / SSL).

    Args:
        server_key: Composite server key.

    Returns:
        InlineKeyboardMarkup: The type-choice keyboard.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=_("checks.kb.tcp"),
                    callback_data=encode_callback_data("chk_ntcp_", server_key),
                ),
                InlineKeyboardButton(
                    text=_("checks.kb.http"),
                    callback_data=encode_callback_data("chk_nhttp_", server_key),
                ),
                InlineKeyboardButton(
                    text=_("checks.kb.ssl"),
                    callback_data=encode_callback_data("chk_nssl_", server_key),
                ),
            ],
            [
                InlineKeyboardButton(
                    text=_("common.back"),
                    callback_data=encode_callback_data("chk_list_", server_key),
                )
            ],
        ]
    )

def get_check_detail_keyboard(
    server_key: str, check_id: str, enabled: bool
) -> InlineKeyboardMarkup:
    """Return the keyboard for a single check's detail screen (toggle / delete / back).

    Args:
        server_key: Composite server key.
        check_id: The check being shown.
        enabled: Whether the check is currently enabled (labels the toggle button).

    Returns:
        InlineKeyboardMarkup: The check-detail keyboard.
    """
    payload = f"{server_key}|{check_id}"
    toggle_label = _("checks.kb.disable") if enabled else _("checks.kb.enable")
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=toggle_label,
                    callback_data=encode_callback_data("chk_tog_", payload),
                ),
                InlineKeyboardButton(
                    text=_("checks.kb.delete"),
                    callback_data=encode_callback_data("chk_del_", payload),
                ),
            ],
            [
                InlineKeyboardButton(
                    text=_("common.back"),
                    callback_data=encode_callback_data("chk_list_", server_key),
                )
            ],
        ]
    )


def get_check_delete_confirm_keyboard(server_key: str, check_id: str) -> InlineKeyboardMarkup:
    """Return the yes/no keyboard confirming deletion of a check.

    Args:
        server_key: Composite server key.
        check_id: The check to delete.

    Returns:
        InlineKeyboardMarkup: The delete-confirm keyboard.
    """
    payload = f"{server_key}|{check_id}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=_("checks.kb.delete_yes"),
                    callback_data=encode_callback_data("chk_delyes_", payload),
                ),
                InlineKeyboardButton(
                    text=_("checks.kb.delete_no"),
                    callback_data=encode_callback_data("chk_show_", payload),
                ),
            ]
        ]
    )


def get_check_input_cancel_keyboard(server_key: str) -> InlineKeyboardMarkup:
    """Return a single Cancel button shown during a check-input FSM step.

    Args:
        server_key: Composite server key (Cancel returns to the checks list).

    Returns:
        InlineKeyboardMarkup: The cancel keyboard.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=_("checks.kb.cancel"),
                    callback_data=encode_callback_data("chk_list_", server_key),
                )
            ]
        ]
    )
