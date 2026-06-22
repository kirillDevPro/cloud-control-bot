"""Routing filter for translated main-menu reply buttons.

Reply-keyboard buttons are matched by their exact visible text, so once a button
label is translated the old ``F.text == "📊 Monitoring"`` filter would only match
one language. :class:`MainMenuButton` matches a menu key against the label in
EVERY supported language, so a handler keeps firing regardless of the user's
current language.

The label set is resolved once at construction time (router import / startup);
the catalog is static, so there is nothing to recompute per update.
"""

from __future__ import annotations

from aiogram.filters import BaseFilter
from aiogram.types import Message

from ..i18n import menu_variants


class MainMenuButton(BaseFilter):
    """Match a Message whose text equals a menu key's label in any language."""

    def __init__(self, key: str) -> None:
        """Resolve and cache every localized label for the menu key.

        Args:
            key: Catalog key of the reply-menu label (e.g. ``"menu.monitoring"``).

        Returns:
            None.
        """
        self.key = key
        self.variants = menu_variants(key)

    async def __call__(self, message: Message) -> bool:
        """Return whether the message text is one of the key's localized labels.

        Args:
            message: Incoming message.

        Returns:
            bool: True if ``message.text`` matches the menu label in any
                supported language.
        """
        return message.text in self.variants
