"""Singleton store for runtime-mutable global settings.

Mirrors the per-user language store in ``src/bot/i18n/store.py``: a module-level
store with an import-time default path (so it is usable before app startup, e.g.
in tests) that :func:`init_runtime_settings` re-points at the configured
``DATA_DIR`` during startup. Values persist to ``data/runtime_settings.json``
with an atomic write so a crash mid-save cannot corrupt the file.

Unlike the language store (one value per user) these are GLOBAL, deployment-wide
settings the admin changes from the bot's Settings menu — currently the
low-balance alert threshold and its on/off switch. Free functions (rather than a
DI-injected repository) let BOTH the Settings handlers AND the ``balance_checker``
background task read/write the values without threading a repository through every
call site; the checker reads the live value on each cycle, so an in-bot change
takes effect without a restart.

Precedence: env/YAML ``BALANCE_THRESHOLD`` seeds the initial threshold, but once
the admin changes any value here the persisted file fully owns both values (the
env/YAML default is then ignored). Delete ``data/runtime_settings.json`` to fall
back to the configured default.

Access is single-process (handlers and background tasks run in the bot's main
process; ping workers never touch this state), so a single lock guarding the
in-memory dict plus a writer lock serializing disk writes is sufficient.
"""

from __future__ import annotations

import json
import logging
import math
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Recognized setting keys (also the JSON object keys on disk).
_KEY_THRESHOLD = "balance_threshold"
_KEY_ALERTS_ENABLED = "balance_alerts_enabled"

# Fallback used before init_runtime_settings() re-seeds from Settings.BALANCE_THRESHOLD;
# matches the Settings field default so the module is sane in tests without startup.
_DEFAULT_THRESHOLD_FALLBACK = 10.0

# Smallest threshold that can ever be stored. A threshold of 0 would mean "alerts on
# but never fire" (no balance is below $0), a silent trap; the on/off switch is the
# way to disable. Every threshold (set, loaded, or seeded) is floored to this.
_MIN_THRESHOLD = 0.01

# Guards the in-memory cache (brief, no I/O — readers only ever take this lock).
_lock = threading.Lock()

# Serializes writers so a slower write cannot land its os.replace after a newer
# write's, leaving the file with a stale snapshot. Held across a single writer's
# whole update+persist; readers never take it, so the file I/O it covers never
# blocks a getter.
_write_lock = threading.Lock()

# In-memory cache of the persisted settings (only recognized keys).
_settings: dict[str, Any] = {}

# Seed for the threshold when it has never been set in-bot. Re-pointed at
# Settings.BALANCE_THRESHOLD by init_runtime_settings() during startup.
_default_threshold: float = _DEFAULT_THRESHOLD_FALLBACK

# Path to the persisted settings. Anchored on the project root (never
# CWD-relative); init_runtime_settings() re-points it at the configured DATA_DIR
# during startup so it lives next to the other data files.
_FILE_PATH: Path = Path(__file__).resolve().parents[2] / "data" / "runtime_settings.json"

# Whether the on-disk file has been loaded into the cache yet.
_loaded: bool = False


def _sanitize_threshold(value: Any, fallback: float) -> float:
    """Coerce a candidate threshold to a finite value floored to ``_MIN_THRESHOLD``.

    Guards every entry point (user input via the store, a hand-edited file, the
    env/YAML seed) so a non-numeric, NaN, or +/-inf value can never poison the
    global alert behavior (inf would make every balance look low; NaN would silence
    alerts forever), and so 0 can never be stored.

    Args:
        value: Candidate value (any type) to sanitize.
        fallback: Finite fallback used when ``value`` is non-numeric or non-finite.

    Returns:
        float: A finite threshold >= ``_MIN_THRESHOLD``.
    """
    try:
        candidate = float(value)
    except (TypeError, ValueError):
        candidate = fallback
    if not math.isfinite(candidate):
        candidate = fallback
    return max(_MIN_THRESHOLD, candidate)


def _read_file() -> dict[str, Any]:
    """Read and validate the runtime-settings file.

    Returns:
        dict[str, Any]: Mapping with only the recognized, well-typed keys present
            in the file. Returns an empty mapping when the file is missing, empty,
            or malformed (the file is left untouched for manual inspection).
    """
    if not _FILE_PATH.exists():
        return {}
    try:
        with open(_FILE_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("Failed to read runtime settings from %s: %s", _FILE_PATH, exc)
        return {}

    if not isinstance(raw, dict):
        logger.warning("Unexpected runtime-settings format in %s: %s", _FILE_PATH, type(raw))
        return {}

    result: dict[str, Any] = {}
    # bool is a subclass of int, so guard the threshold against a stray True/False.
    # A non-finite stored value (json parses Infinity/NaN) is skipped, so the seed
    # default applies instead of a poisoned threshold.
    threshold = raw.get(_KEY_THRESHOLD)
    if (
        isinstance(threshold, (int, float))
        and not isinstance(threshold, bool)
        and math.isfinite(threshold)
    ):
        result[_KEY_THRESHOLD] = max(_MIN_THRESHOLD, float(threshold))
    enabled = raw.get(_KEY_ALERTS_ENABLED)
    if isinstance(enabled, bool):
        result[_KEY_ALERTS_ENABLED] = enabled
    return result


def _persist(data: dict[str, Any]) -> bool:
    """Atomically write a settings snapshot to disk.

    Uses a write-to-temp-then-rename pattern (``os.replace`` is atomic on Windows
    and Unix) so a partial write can never corrupt the live file. Takes an explicit
    snapshot (captured under ``_lock`` by the caller) and is itself LOCK-FREE, so the
    potentially slow disk write never blocks concurrent getters.

    Args:
        data: Snapshot of the settings mapping to write.

    Returns:
        bool: True if the snapshot was durably written to disk; False if the write
            failed (the error is logged; the in-memory cache is unaffected here).
    """
    temp_path: str | None = None
    try:
        _FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(
            dir=_FILE_PATH.parent, prefix=f".{_FILE_PATH.stem}_", suffix=".tmp"
        )
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            # allow_nan=False so a non-finite value can never be written (defense in
            # depth — the setters already sanitize to finite).
            json.dump(data, f, ensure_ascii=False, indent=2, allow_nan=False)
        os.replace(temp_path, _FILE_PATH)
        temp_path = None
        return True
    except (OSError, ValueError) as exc:
        logger.error("Failed to persist runtime settings to %s: %s", _FILE_PATH, exc)
        return False
    finally:
        if temp_path is not None:
            try:
                os.unlink(temp_path)
            except OSError:
                pass


def init_runtime_settings(file_path: Path | None = None, *, default_threshold: float) -> None:
    """Point the store at the configured file and load it into memory.

    Called once during app startup with ``settings.get_runtime_settings_file()`` and
    ``settings.BALANCE_THRESHOLD`` so the file lives next to the other data files and
    the threshold falls back to the configured default until the admin overrides it
    in-bot. No file is written here — the file is created lazily on the first change.

    Args:
        file_path: Full path to the runtime-settings JSON file. When None, keeps the
            current path (the project-root default).
        default_threshold: Seed threshold used until one is set in-bot (the env/YAML
            ``BALANCE_THRESHOLD`` value); sanitized to a finite value no lower than
            ``_MIN_THRESHOLD``.

    Returns:
        None.
    """
    global _FILE_PATH, _settings, _default_threshold, _loaded
    # Set the path and read the file BEFORE taking _lock: init runs once,
    # single-threaded, at startup, and _lock must stay brief and I/O-free (the
    # getters hold it). Only the in-memory assignment happens under the lock.
    if file_path is not None:
        _FILE_PATH = Path(file_path)
    new_default = _sanitize_threshold(default_threshold, _DEFAULT_THRESHOLD_FALLBACK)
    loaded = _read_file()
    with _lock:
        _default_threshold = new_default
        _settings = loaded
        _loaded = True
    logger.info(
        "Runtime settings initialized at %s (threshold=%.2f, alerts=%s)",
        _FILE_PATH,
        _settings.get(_KEY_THRESHOLD, _default_threshold),
        _settings.get(_KEY_ALERTS_ENABLED, True),
    )


def _ensure_loaded() -> None:
    """Lazily load the file on first access if init was never called.

    Keeps the module usable in tests that call the accessors without running
    startup. Caller MUST hold ``_lock``.

    Returns:
        None.
    """
    global _settings, _loaded
    if not _loaded:
        logger.warning(
            "Runtime settings accessed before init_runtime_settings(); lazy-loading %s",
            _FILE_PATH,
        )
        _settings = _read_file()
        _loaded = True


def get_balance_threshold() -> float:
    """Return the current low-balance alert threshold in USD.

    Returns:
        float: The in-bot threshold when set, otherwise the seeded env/YAML default.
    """
    with _lock:
        _ensure_loaded()
        return float(_settings.get(_KEY_THRESHOLD, _default_threshold))


def are_balance_alerts_enabled() -> bool:
    """Return whether low-balance alerts are currently enabled.

    Returns:
        bool: True unless the admin has switched alerts off in-bot (default True).
    """
    with _lock:
        _ensure_loaded()
        return bool(_settings.get(_KEY_ALERTS_ENABLED, True))


def set_balance_threshold(value: float) -> bool:
    """Persist a new low-balance threshold and enable alerts.

    Choosing a threshold implies wanting the alerts, so this also turns alerts ON
    (the explicit off switch is :func:`set_balance_alerts_enabled`). The in-memory
    cache is always updated (so the change takes effect immediately for the running
    process and the next ``balance_checker`` cycle); the boolean reports only whether
    the durable disk write succeeded.

    Args:
        value: New threshold in USD; sanitized to a finite value >= ``_MIN_THRESHOLD``.
            Non-numeric and non-finite inputs fall back to the current default before
            the minimum threshold floor is applied.

    Returns:
        bool: True if the change was durably persisted to disk; False if only the
            in-memory cache was updated (the disk write failed and was logged).
    """
    sanitized = _sanitize_threshold(value, _default_threshold)
    with _write_lock:
        with _lock:
            _ensure_loaded()
            _settings[_KEY_THRESHOLD] = sanitized
            _settings[_KEY_ALERTS_ENABLED] = True
            snapshot = dict(_settings)
        return _persist(snapshot)


def set_balance_alerts_enabled(enabled: bool) -> bool:
    """Persist the low-balance alert on/off switch.

    The in-memory cache is always updated (so the change takes effect immediately for
    the running process and the next ``balance_checker`` cycle); the boolean reports
    only whether the durable disk write succeeded. The current effective threshold is
    materialized into the snapshot too, so the persisted file always carries BOTH
    values — once any setting is changed in-bot the file fully owns the contract and
    a later env/YAML change cannot silently move the threshold.

    Args:
        enabled: True to send low-balance alerts, False to silence them.

    Returns:
        bool: True if the change was durably persisted to disk; False if only the
            in-memory cache was updated (the disk write failed and was logged).
    """
    with _write_lock:
        with _lock:
            _ensure_loaded()
            _settings[_KEY_ALERTS_ENABLED] = bool(enabled)
            # Complete the snapshot so the file carries the threshold too (see docstring).
            _settings.setdefault(_KEY_THRESHOLD, _default_threshold)
            snapshot = dict(_settings)
        return _persist(snapshot)
