"""Settings router for the hub screen and its configurable sections.

The Settings reply button lands on a small inline "hub" menu (one button per
settings section), and tapping a section edits that hub into the selected
section. Current sections are the language picker and low-balance alert controls:
the alert section can toggle notifications, apply a preset threshold, or enter a
custom threshold through the FSM below. A new section needs one more entry in
``SETTINGS_SECTIONS`` plus matching open/back callbacks here. The ``/language``
command is a shortcut straight to the language section.
"""

import asyncio
import logging
import math

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ..filters import MainMenuButton
from ..i18n import (
    _,
    LANGUAGE_NAMES,
    SUPPORTED_LANGUAGES,
    menu_variants,
    set_current_language,
    set_user_language,
)
from ..keyboards import (
    SETTINGS_SECTIONS,
    get_balance_alerts_keyboard,
    get_balance_threshold_cancel_keyboard,
    get_language_keyboard,
    get_main_menu_keyboard,
    get_settings_menu_keyboard,
)
from ..utils import (
    handle_telegram_errors,
    reset_screen_from_callback,
    safe_edit_message,
    show_screen,
)
from ..utils.rich import blocks, stack
from ...storage.runtime_settings import (
    are_balance_alerts_enabled,
    get_balance_threshold,
    set_balance_alerts_enabled,
    set_balance_threshold,
)
from ...background_tasks.balance_checker import reset_low_balance_cooldown

logger = logging.getLogger(__name__)

# Router for the settings hub, the language and balance-alerts sections, and their
# selection callbacks.
settings_router = Router(name="settings")


class BalanceThresholdForm(StatesGroup):
    """FSM states for the optional custom low-balance threshold text input."""

    waiting_for_value = State()


# Localized labels of every main-menu reply button across all languages. Used to
# detect a menu tap during custom-threshold input so the modal flow cancels cleanly
# instead of swallowing the tap.
_MAIN_MENU_LABELS: frozenset[str] = frozenset(
    label
    for key in ("menu.monitoring", "menu.servers", "menu.balance", "menu.settings")
    for label in menu_variants(key)
)


def _menu_text() -> str:
    """Build the settings hub screen body, listing each section with a description.

    Returns:
        str: The HTML hub text — title, the choose-a-section prompt, then one
            ``label — description`` line per section in SETTINGS_SECTIONS.
    """
    sections = stack(
        *(f"{_(label_key)} — {_(desc_key)}" for label_key, desc_key, _cb in SETTINGS_SECTIONS)
    )
    return blocks(_("settings.title"), _("settings.choose_section"), sections)


def _language_text(language: str) -> str:
    """Build the language-section screen body for a language.

    Args:
        language: Language code whose proper name is shown as the current one.

    Returns:
        str: The HTML language-section text with a settings/language breadcrumb
            followed by the current language.
    """
    breadcrumb = f"{_('settings.title')} › {_('settings.section_language')}"
    return blocks(breadcrumb, _("settings.language_current", current=LANGUAGE_NAMES[language]))


def _balance_alerts_text(enabled: bool, threshold: float) -> str:
    """Build the balance-alerts section body.

    Args:
        enabled: Whether low-balance alerts are currently on (status line).
        threshold: The current threshold in USD (shown in the threshold line).

    Returns:
        str: The HTML section text — settings/balance breadcrumb, the on/off status,
            the current threshold and its hint, then the choose-a-value prompt.
    """
    breadcrumb = f"{_('settings.title')} › {_('settings.section_balance')}"
    status = _("settings.balance_status_on") if enabled else _("settings.balance_status_off")
    return blocks(
        breadcrumb,
        stack(
            status,
            _("settings.balance_threshold_current", value=threshold),
            _("settings.balance_threshold_hint"),
        ),
        _("settings.balance_choose"),
    )


def _balance_prompt_text() -> str:
    """Build the custom-threshold input prompt body.

    Returns:
        str: The HTML prompt asking for a numeric USD value.
    """
    return blocks(_("settings.balance_prompt_title"), _("settings.balance_prompt_body"))


def _balance_invalid_text() -> str:
    """Build the re-prompt shown when the typed custom value is not a positive number.

    Returns:
        str: The HTML prompt title followed by the invalid-value hint.
    """
    return blocks(_("settings.balance_prompt_title"), _("settings.balance_invalid"))


@settings_router.message(BalanceThresholdForm.waiting_for_value)
async def on_custom_threshold_input(message: Message, state: FSMContext) -> None:
    """Handle the custom threshold the admin types (modal input state).

    Registered before the menu-button handlers so it intercepts EVERY message while
    waiting for the value:
    - a valid positive number is saved (which also enables alerts), then the section
      is re-shown;
    - a main-menu button tap cancels the flow and returns to the main menu (so a tap
      is never silently swallowed);
    - anything else re-prompts and keeps the flow open (the inline Cancel stays).

    Args:
        message: The incoming message while in the waiting-for-value state.
        state: FSM context used to clear the state once the flow ends.

    Returns:
        None.
    """
    # A main-menu button tap leaves the modal cleanly instead of being eaten.
    if message.text in _MAIN_MENU_LABELS:
        await state.clear()
        await show_screen(message, _("settings.balance_cancelled"), get_main_menu_keyboard())
        return

    raw = (message.text or "").strip().replace(",", ".")
    try:
        value = float(raw)
    except ValueError:
        value = None
    # Require a finite, positive amount: 0/negative would never alert (the on/off
    # switch is the way to disable) and NaN/inf would poison global alert behavior.
    if value is None or not math.isfinite(value) or value <= 0:
        await show_screen(message, _balance_invalid_text(), get_balance_threshold_cancel_keyboard())
        return

    persisted = await asyncio.to_thread(set_balance_threshold, value)
    # Setting a threshold (re-)enables alerts; re-arm the cooldown so a still-low
    # balance is warned about promptly instead of waiting out a leftover cooldown.
    reset_low_balance_cooldown()
    await state.clear()

    # Render the value actually stored (it may have been floored), not the raw input.
    body = _balance_alerts_text(True, get_balance_threshold())
    if not persisted:
        # Mirror the language flow: be honest when the change is in-memory only.
        body = blocks(_("settings.balance_not_saved_notice"), body)
    await show_screen(message, body, get_balance_alerts_keyboard(True))


@settings_router.message(MainMenuButton("menu.settings"))
async def cmd_settings(message: Message) -> None:
    """Handle the Settings reply-keyboard button: show the settings hub.

    Args:
        message: Incoming reply-keyboard tap message.

    Returns:
        None.
    """
    # Sent as the single live section screen (deletes this chat's previous one).
    await show_screen(message, _menu_text(), get_settings_menu_keyboard())


@settings_router.message(Command("language"))
async def cmd_language(message: Message, language: str) -> None:
    """Handle the /language command: jump straight to the language section.

    Args:
        message: Incoming /language command message.
        language: The user's active language (injected by LanguageMiddleware).

    Returns:
        None.
    """
    await show_screen(message, _language_text(language), get_language_keyboard(language))


@settings_router.callback_query(F.data == "settings_lang")
@handle_telegram_errors
async def callback_open_language(callback: CallbackQuery, language: str) -> None:
    """Open the language section from the settings hub (edits the hub in place).

    Args:
        callback: Callback query from the hub's language button.
        language: The user's active language (injected by LanguageMiddleware).

    Returns:
        None.
    """
    await safe_edit_message(callback, _language_text(language), get_language_keyboard(language))
    await callback.answer()


@settings_router.callback_query(F.data == "settings_back")
@handle_telegram_errors
async def callback_settings_back(callback: CallbackQuery) -> None:
    """Return from a settings section to the settings hub (edits in place).

    Args:
        callback: Callback query from a section's Back button.

    Returns:
        None.
    """
    await safe_edit_message(callback, _menu_text(), get_settings_menu_keyboard())
    await callback.answer()


@settings_router.callback_query(F.data.startswith("set_lang_"))
@handle_telegram_errors
async def callback_set_language(callback: CallbackQuery) -> None:
    """Persist the chosen language and drop to one clean main-menu screen in it.

    Stores the choice, activates it for the rest of this update, then replaces the
    language picker with a single persistent main-menu screen rendered in the new
    language. Reply-keyboard labels cannot be edited in place, so a language switch
    must re-send the main menu; routing that through ``reset_screen_from_callback``
    removes the picker (even when the single-screen tracker is stale after a
    restart) and sends the menu UNtracked, so its reply keyboard survives later
    navigation — leaving the chat with one clean screen instead of a leftover
    (still interactive) picker plus a separate notice.

    Args:
        callback: Callback query whose data is ``set_lang_<code>``.

    Returns:
        None.
    """
    new_language = callback.data.removeprefix("set_lang_")
    if new_language not in SUPPORTED_LANGUAGES:
        await callback.answer(_("common.unknown_operation"))
        logger.warning("Unknown language in callback_data: %r", callback.data)
        return

    # Persist off the event loop (the store does a small atomic file write), then
    # activate for the rest of this update so every _() below (toast, settings
    # message, keyboards) renders in the newly chosen language.
    persisted = await asyncio.to_thread(set_user_language, callback.from_user.id, new_language)
    # Apply for this running process regardless, so the rest of this update (and the
    # session) renders in the chosen language.
    set_current_language(new_language)

    if persisted:
        await callback.answer(_("settings.language_changed"))
    else:
        # The disk write failed (logged by the store): the change is in-memory only
        # and will reset on restart. Tell the user instead of claiming success.
        logger.warning(
            "Language preference for user %s applied in-memory only (not persisted)",
            callback.from_user.id,
        )
        await callback.answer(_("settings.language_not_saved"), show_alert=True)

    # Reply-keyboard labels cannot be edited in place, so a language switch must
    # re-send the main menu. reset_screen_from_callback removes the picker and sends
    # the menu as a PERSISTENT (untracked) screen, so its reply keyboard is not lost
    # when the user later navigates to another section.
    await reset_screen_from_callback(
        callback, _("settings.menu_updated"), get_main_menu_keyboard()
    )


@settings_router.callback_query(F.data == "settings_balance")
@handle_telegram_errors
async def callback_open_balance(callback: CallbackQuery, state: FSMContext) -> None:
    """Open the balance-alerts section from the hub (edits the hub in place).

    Also clears any pending custom-input state, so this doubles as the Cancel target
    for the custom-threshold prompt.

    Args:
        callback: Callback query from the hub's balance button (or the prompt Cancel).
        state: FSM context cleared in case a custom-input flow was in progress.

    Returns:
        None.
    """
    await state.clear()
    enabled = are_balance_alerts_enabled()
    threshold = get_balance_threshold()
    await safe_edit_message(
        callback, _balance_alerts_text(enabled, threshold), get_balance_alerts_keyboard(enabled)
    )
    await callback.answer()


@settings_router.callback_query(F.data.in_({"bal_alerts_on", "bal_alerts_off"}))
@handle_telegram_errors
async def callback_toggle_balance_alerts(callback: CallbackQuery) -> None:
    """Turn low-balance alerts on or off and re-render the section in place.

    Args:
        callback: Callback query whose data is ``bal_alerts_on`` / ``bal_alerts_off``.

    Returns:
        None.
    """
    enable = callback.data == "bal_alerts_on"
    persisted = await asyncio.to_thread(set_balance_alerts_enabled, enable)
    if enable:
        # Re-arm the cooldown so re-enabling warns promptly about a still-low balance.
        reset_low_balance_cooldown()
    threshold = get_balance_threshold()
    await safe_edit_message(
        callback, _balance_alerts_text(enable, threshold), get_balance_alerts_keyboard(enable)
    )
    if persisted:
        await callback.answer(
            _("settings.balance_enabled_toast") if enable else _("settings.balance_disabled_toast")
        )
    else:
        await callback.answer(_("settings.balance_not_saved_toast"), show_alert=True)


@settings_router.callback_query(F.data.startswith("bal_thr_set_"))
@handle_telegram_errors
async def callback_set_threshold_preset(callback: CallbackQuery) -> None:
    """Apply a preset threshold value (which also enables alerts) and re-render.

    Args:
        callback: Callback query whose data is ``bal_thr_set_<amount>``.

    Returns:
        None.
    """
    raw = callback.data.removeprefix("bal_thr_set_")
    try:
        value = float(raw)
    except ValueError:
        await callback.answer(_("common.unknown_operation"))
        logger.warning("Invalid threshold preset in callback_data: %r", callback.data)
        return

    # set_balance_threshold auto-enables alerts, so the re-rendered section is "on".
    persisted = await asyncio.to_thread(set_balance_threshold, value)
    # Changing the threshold (re-)enables alerts; re-arm the cooldown for a prompt warning.
    reset_low_balance_cooldown()
    # Render/announce the value actually stored (the store may floor it).
    stored = get_balance_threshold()
    await safe_edit_message(
        callback, _balance_alerts_text(True, stored), get_balance_alerts_keyboard(True)
    )
    if persisted:
        await callback.answer(_("settings.balance_threshold_set_toast", value=stored))
    else:
        await callback.answer(_("settings.balance_not_saved_toast"), show_alert=True)


@settings_router.callback_query(F.data == "bal_thr_custom")
@handle_telegram_errors
async def callback_custom_threshold(callback: CallbackQuery, state: FSMContext) -> None:
    """Start the custom-threshold text-input flow (edits the section into a prompt).

    Args:
        callback: Callback query from the "custom value" button.
        state: FSM context set to the waiting-for-value state.

    Returns:
        None.
    """
    await state.set_state(BalanceThresholdForm.waiting_for_value)
    await safe_edit_message(callback, _balance_prompt_text(), get_balance_threshold_cancel_keyboard())
    await callback.answer()
