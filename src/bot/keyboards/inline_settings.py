"""Inline keyboard builders and constants for settings screens."""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from ..i18n import _, LANGUAGE_NAMES, SUPPORTED_LANGUAGES


# Settings hub sections: (label i18n key, description i18n key, callback_data).
# Single source of truth for the hub — both the hub keyboard (label + callback) and
# the section list in the hub message text (label + description) are built from
# this, so a new setting is added in exactly one place.
SETTINGS_SECTIONS: list[tuple[str, str, str]] = [
    ("settings.section_language", "settings.section_language_desc", "settings_lang"),
    ("settings.section_balance", "settings.section_balance_desc", "settings_balance"),
]

# Threshold presets (USD) offered as one-tap buttons in the balance-alerts section.
BALANCE_THRESHOLD_PRESETS: tuple[int, ...] = (50, 100, 500, 1000, 2000)


def get_settings_menu_keyboard() -> InlineKeyboardMarkup:
    """Build the settings hub (top-level settings menu) inline keyboard.

    One button per entry in :data:`SETTINGS_SECTIONS` (the single source of truth
    for the hub's sections, shared with the hub message text). Tapping a section
    opens it in place (the message is edited, not replaced); the section's "Back"
    button returns to this hub.

    Returns:
        InlineKeyboardMarkup: One row per settings section.
    """
    keyboard = [
        [InlineKeyboardButton(text=_(label_key), callback_data=callback_data)]
        for label_key, desc_key, callback_data in SETTINGS_SECTIONS
    ]

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_language_keyboard(current_language: str) -> InlineKeyboardMarkup:
    """Build the language-picker inline keyboard for the language section.

    Two language buttons per row; the active language is marked with bullets.
    Language names are proper nouns shown identically in every UI language, so they
    are not translated. The callback encodes the target language code
    (``set_lang_en`` / ``set_lang_ru``). A trailing Back row uses ``settings_back``
    so the settings router edits the same message back to the hub.

    Args:
        current_language: The user's currently active language code.

    Returns:
        InlineKeyboardMarkup: Language buttons two per row, then a Back row.
    """
    buttons: list[InlineKeyboardButton] = []
    for language in SUPPORTED_LANGUAGES:
        label = LANGUAGE_NAMES[language]
        if language == current_language:
            label = f"• {label} •"
        buttons.append(InlineKeyboardButton(text=label, callback_data=f"set_lang_{language}"))

    # Two languages per row (the last row holds one button if the count is odd).
    keyboard: list[list[InlineKeyboardButton]] = [
        buttons[i : i + 2] for i in range(0, len(buttons), 2)
    ]
    # Back returns to the settings hub by editing this picker in place.
    keyboard.append([InlineKeyboardButton(text=_("common.back"), callback_data="settings_back")])

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_balance_alerts_keyboard(enabled: bool) -> InlineKeyboardMarkup:
    """Build the balance-alerts settings section keyboard.

    Layout: an on/off toggle row (label + callback flip with the current state), the
    threshold presets three-per-row, a "custom value" row that starts the text-input
    flow, and a Back row that edits this section back to the settings hub.

    Args:
        enabled: Whether low-balance alerts are currently on (decides the toggle label
            and callback).

    Returns:
        InlineKeyboardMarkup: The balance-alerts section keyboard.
    """
    # Toggle reflects the current state: show "turn off" when on, "turn on" when off.
    if enabled:
        toggle = InlineKeyboardButton(
            text=_("settings.balance_btn_off"), callback_data="bal_alerts_off"
        )
    else:
        toggle = InlineKeyboardButton(
            text=_("settings.balance_btn_on"), callback_data="bal_alerts_on"
        )

    keyboard: list[list[InlineKeyboardButton]] = [[toggle]]

    # Preset amounts, three per row. Labels are plain "$N" (numbers are not localized).
    preset_buttons = [
        InlineKeyboardButton(text=f"${value}", callback_data=f"bal_thr_set_{value}")
        for value in BALANCE_THRESHOLD_PRESETS
    ]
    for i in range(0, len(preset_buttons), 3):
        keyboard.append(preset_buttons[i : i + 3])

    keyboard.append(
        [InlineKeyboardButton(text=_("settings.balance_btn_custom"), callback_data="bal_thr_custom")]
    )
    # Back edits this section back to the settings hub (handled by settings_back).
    keyboard.append([InlineKeyboardButton(text=_("common.back"), callback_data="settings_back")])

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_balance_threshold_cancel_keyboard() -> InlineKeyboardMarkup:
    """Build the cancel keyboard shown while waiting for a custom threshold value.

    The single Cancel button reuses the ``settings_balance`` callback, so cancelling
    reopens the balance-alerts section (whose handler also clears the input state).

    Returns:
        InlineKeyboardMarkup: A one-button cancel keyboard.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=_("kb.cancel"), callback_data="settings_balance")]
        ]
    )
