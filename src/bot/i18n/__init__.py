"""Internationalization (i18n) for the bot — English + Russian.

Public API:

* :func:`t` / :func:`_` — resolve a key in the active (context-var) language.
* :func:`translate` / :func:`translate_plural` — resolve a key in an explicit
  language (used by per-recipient background notifications).
* :func:`plural` — resolve a plural-aware key in the active language.
* :func:`set_current_language` / :func:`get_current_language` — manage the active
  language (set by :class:`~src.bot.middlewares.language.LanguageMiddleware`).
* :func:`menu_variants` — every localized label of a reply-menu key (for the
  routing filter).
* :func:`translate_error` / :func:`localize_error` — render a domain exception's
  user-facing detail in an explicit / the active language (English ``str()``
  fallback for unmapped exceptions).
* :data:`SUPPORTED_LANGUAGES`, :data:`DEFAULT_LANGUAGE`, :data:`LANGUAGE_NAMES`.
* :func:`init_language_store`, :func:`get_user_language`, :func:`set_user_language`
  — the persisted per-user language store.
"""

from .errors import localize_error, translate_error
from .store import get_user_language, init_language_store, set_user_language
from .translator import (
    DEFAULT_LANGUAGE,
    LANGUAGE_NAMES,
    SUPPORTED_LANGUAGES,
    _,
    get_current_language,
    menu_variants,
    normalize_language,
    plural,
    set_current_language,
    t,
    translate,
    translate_plural,
)

__all__ = [
    "DEFAULT_LANGUAGE",
    "LANGUAGE_NAMES",
    "SUPPORTED_LANGUAGES",
    "_",
    "get_current_language",
    "get_user_language",
    "init_language_store",
    "menu_variants",
    "normalize_language",
    "plural",
    "localize_error",
    "set_current_language",
    "set_user_language",
    "t",
    "translate",
    "translate_error",
    "translate_plural",
]
