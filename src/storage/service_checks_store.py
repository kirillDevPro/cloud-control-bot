"""Singleton store for per-server service-check definitions.

Mirrors the per-user language store in ``src/bot/i18n/store.py``: a module-level, keyed
store with an import-time default path (usable before startup, e.g. in tests) that
:func:`init_service_checks_store` re-points at the configured file during startup.
Definitions persist to ``data/service_checks.json`` (``{composite_key: [check, ...]}``)
with an atomic write so a crash mid-save cannot corrupt the file.

Free functions (rather than a DI-injected repository) let BOTH the checks router AND the
``service_checks_task`` background task read/write the config without threading a
repository through every call site, and let a chat change take effect on the next check
cycle with no restart — the same reason ``runtime_settings`` is shaped this way.

Access is single-process: the checks task runs in the bot's MAIN process, not the ping
workers, so a single lock guarding the in-memory cache plus a writer lock serializing
disk writes is sufficient. (This is exactly why the whole feature runs in the main
process — this store would be invisible to a worker process.)

Corruption philosophy — attempt backup-and-PRESERVE, never deliberately reset-to-empty: on
a malformed file the reader tries to rename the original to a timestamped ``.backup`` before
returning ``{}``. A successful rename prevents the first subsequent write from replacing the
corrupt original with an almost-empty snapshot. This is the deliberate departure from the
language store, whose reset-to-empty-on-corruption is harmless for a per-user preference but
would silently destroy hand-built check config here.

A transient ``OSError`` is handled differently from malformed content: the intact file is
left in place, reads are retried on later accesses, and every mutator refuses both the
in-memory change and the disk write while ``_load_failed`` remains set. This prevents an
empty cache created by a failed read from replacing the real configuration.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ..models.service_check import CheckDefinition

logger = logging.getLogger(__name__)

# Guards the in-memory cache (brief, no I/O — readers only ever take this lock).
_lock = threading.Lock()

# Serializes writers so a slower write cannot land its os.replace after a newer write's,
# leaving the file with a stale snapshot. Held across a single writer's whole
# update+persist; readers never take it, so the file I/O never blocks a reader.
_write_lock = threading.Lock()

# In-memory cache: composite_key -> list of check definitions.
_checks: dict[str, list[CheckDefinition]] = {}

# Path to the persisted config. Anchored on the project root (never CWD-relative);
# init_service_checks_store() re-points it at the configured DATA_DIR during startup.
_FILE_PATH: Path = Path(__file__).resolve().parents[2] / "data" / "service_checks.json"

# Whether the on-disk file has been loaded into the cache yet.
_loaded: bool = False

# True when the last read of an EXISTING file failed transiently (an OSError, not corruption):
# the cache is then empty but the real file is intact, so setters must REFUSE to persist (which
# would os.replace a near-empty snapshot over every server's checks). Cleared once a read
# succeeds. Corruption is handled separately by backup-and-preserve, so it does not set this.
_load_failed: bool = False


def _read_file() -> dict[str, list[CheckDefinition]]:
    """Read and validate the service-checks file.

    On a malformed file, attempts to rename the original to a timestamped ``.backup`` before
    returning ``{}`` — see the module docstring for why the rename is load-bearing.

    Returns:
        dict[str, list[CheckDefinition]]: Mapping of composite_key to its check list.
            Malformed individual checks are skipped (the rest of a server's list is kept).
            Malformed whole-file content returns ``{}`` after a backup attempt; a transient
            read error returns ``{}``, sets ``_load_failed``, and leaves the original untouched.
    """
    global _load_failed
    _load_failed = False
    try:
        with open(_FILE_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError:
        # No file yet (fresh install) — a normal empty start, NOT a load failure.
        return {}
    except OSError as exc:
        # A transient read error (permission, stat, network FS) is NOT corruption and must not
        # abort startup. Flag the failed load so setters refuse to persist (a later os.replace
        # would otherwise overwrite the intact-but-unread file with a near-empty snapshot); the
        # next access retries the read. Handled inside the try so even the open() itself is
        # covered.
        logger.error("Failed to read service checks from %s: %s", _FILE_PATH, exc)
        _load_failed = True
        return {}
    except json.JSONDecodeError as exc:
        logger.critical("Service-checks file %s is malformed: %s", _FILE_PATH, exc)
        _backup_corrupt_file()
        return {}

    if not isinstance(raw, dict):
        logger.critical("Unexpected service-checks format in %s: %s", _FILE_PATH, type(raw))
        _backup_corrupt_file()
        return {}

    result: dict[str, list[CheckDefinition]] = {}
    for composite_key, checks in raw.items():
        if not isinstance(composite_key, str) or not isinstance(checks, list):
            continue
        parsed: list[CheckDefinition] = []
        for entry in checks:
            try:
                parsed.append(CheckDefinition(**entry))
            except (ValidationError, TypeError) as exc:
                # Skip one malformed check, keep the rest of the server's list.
                logger.warning(
                    "Dropping malformed check for %s in %s: %s", composite_key, _FILE_PATH, exc
                )
        if parsed:
            result[composite_key] = parsed
    return result


def _backup_corrupt_file() -> None:
    """Rename the corrupt file to a timestamped ``.backup`` so a later write cannot erase it.

    Renaming moves the original OUT of ``_persist``'s ``os.replace`` target path, which is
    what makes the preserve real (an almost-empty snapshot would otherwise overwrite it).

    Returns:
        None.
    """
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = _FILE_PATH.with_suffix(f".{timestamp}.backup")
        _FILE_PATH.rename(backup_path)
        logger.critical("Backed up corrupt service-checks file to %s", backup_path)
    except OSError as exc:
        logger.error("Failed to back up corrupt service-checks file %s: %s", _FILE_PATH, exc)


def _persist(snapshot: dict[str, list[CheckDefinition]]) -> bool:
    """Atomically write a config snapshot to disk.

    Uses write-to-temp-then-rename (``os.replace`` is atomic on Windows and Unix) so a
    partial write can never corrupt the live file. Takes an explicit snapshot (captured
    under ``_lock`` by the caller) and is itself LOCK-FREE, so the disk write never blocks
    concurrent readers.

    Args:
        snapshot: Snapshot of the composite_key -> check-list mapping to write.

    Returns:
        bool: True if the snapshot was durably written; False on write failure (logged).
    """
    serializable = {
        key: [check.model_dump(mode="json") for check in checks]
        for key, checks in snapshot.items()
    }
    temp_path: str | None = None
    try:
        _FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(
            dir=_FILE_PATH.parent, prefix=f".{_FILE_PATH.stem}_", suffix=".tmp"
        )
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(serializable, f, ensure_ascii=False, indent=2)
        os.replace(temp_path, _FILE_PATH)
        temp_path = None
        return True
    except OSError as exc:
        logger.error("Failed to persist service checks to %s: %s", _FILE_PATH, exc)
        return False
    finally:
        if temp_path is not None:
            try:
                os.unlink(temp_path)
            except OSError:
                pass


def init_service_checks_store(file_path: Path | None = None) -> None:
    """Point the store at the configured file and load it into memory.

    Called once during app startup with ``settings.get_service_checks_file()`` so the
    config lives next to the other data files regardless of the working directory.

    Args:
        file_path: Full path to the service-checks JSON file. When None, keeps the current
            path (the project-root default).

    Returns:
        None.
    """
    global _FILE_PATH, _checks, _loaded
    # Set the path and read the file BEFORE taking _lock: init runs once, single-threaded,
    # at startup, and _lock must stay brief and I/O-free (readers hold it).
    if file_path is not None:
        _FILE_PATH = Path(file_path)
    loaded = _read_file()
    with _lock:
        _checks = loaded
        _loaded = True
    logger.info(
        "Service-checks store initialized at %s (%d server(s) configured)",
        _FILE_PATH,
        len(_checks),
    )


def _ensure_loaded() -> None:
    """Lazily load the file on first access if init was never called.

    Keeps the module usable in tests that call the accessors without running startup.
    Caller MUST hold ``_lock``.

    Returns:
        None.
    """
    global _checks, _loaded
    if not _loaded:
        logger.warning(
            "Service-checks store accessed before init_service_checks_store(); lazy-loading %s",
            _FILE_PATH,
        )
        _checks = _read_file()
        _loaded = True
    elif _load_failed:
        # A prior read failed transiently; retry so a recovered file is picked up (and so
        # setters stop being blocked once it reads cleanly).
        _checks = _read_file()


def get_checks(composite_key: str) -> list[CheckDefinition]:
    """Return the checks configured for a server.

    Args:
        composite_key: The server's composite key (``provider_alias:server_id``).

    Returns:
        list[CheckDefinition]: A shallow copy of the server's checks (empty if none), so a
            caller iterating it is unaffected by a concurrent edit.
    """
    with _lock:
        _ensure_loaded()
        return list(_checks.get(composite_key, []))


def get_all_checks() -> dict[str, list[CheckDefinition]]:
    """Return a snapshot of every server's checks (the per-cycle snapshot for the task).

    Returns:
        dict[str, list[CheckDefinition]]: A fresh mapping with per-server list copies, so
            the checks task can iterate a stable snapshot while edits continue.
    """
    with _lock:
        _ensure_loaded()
        return {key: list(checks) for key, checks in _checks.items()}


def add_check(composite_key: str, definition: CheckDefinition) -> bool:
    """Append a new check for a server and persist.

    If the last read failed transiently, the operation is refused before changing memory or
    disk. Otherwise the in-memory cache is updated for the next check cycle even when the
    subsequent durable write fails.

    Args:
        composite_key: The server's composite key.
        definition: The check to add.

    Returns:
        bool: True if durably persisted; False if the load guard refused the operation or
            persistence failed after the in-memory cache was updated.
    """
    with _write_lock:
        with _lock:
            _ensure_loaded()
            if _load_failed:
                logger.error("Not persisting check add for %s: store file unreadable", composite_key)
                return False
            _checks.setdefault(composite_key, []).append(definition)
            snapshot = {key: list(checks) for key, checks in _checks.items()}
        return _persist(snapshot)


def update_check(composite_key: str, check_id: str, **fields: Any) -> bool:
    """Update fields of an existing check and persist.

    Args:
        composite_key: The server's composite key.
        check_id: The check to update.
        **fields: Field values to overwrite on the check (validated by the model).

    Returns:
        bool: True if the check was found, updated, and durably persisted; False if the
            load guard refused the operation, the check was not found, or the disk write
            failed. Memory is unchanged on guard/not-found failures and retains the update
            when only the disk write fails.
    """
    with _write_lock:
        with _lock:
            _ensure_loaded()
            if _load_failed:
                logger.error("Not persisting check update for %s: store file unreadable", composite_key)
                return False
            checks = _checks.get(composite_key)
            if not checks:
                return False
            for i, check in enumerate(checks):
                if check.check_id == check_id:
                    checks[i] = check.model_copy(update=fields)
                    break
            else:
                return False
            snapshot = {key: list(cs) for key, cs in _checks.items()}
        return _persist(snapshot)


def delete_check(composite_key: str, check_id: str) -> bool:
    """Delete a single check and persist.

    Args:
        composite_key: The server's composite key.
        check_id: The check to delete.

    Returns:
        bool: True if the check was found, removed, and durably persisted; False if the
            load guard refused the operation, the check was not found, or the disk write
            failed. Memory is unchanged on guard/not-found failures and retains the deletion
            when only the disk write fails.
    """
    with _write_lock:
        with _lock:
            _ensure_loaded()
            if _load_failed:
                logger.error("Not persisting check delete for %s: store file unreadable", composite_key)
                return False
            checks = _checks.get(composite_key)
            if not checks:
                return False
            remaining = [c for c in checks if c.check_id != check_id]
            if len(remaining) == len(checks):
                return False
            if remaining:
                _checks[composite_key] = remaining
            else:
                del _checks[composite_key]
            snapshot = {key: list(cs) for key, cs in _checks.items()}
        return _persist(snapshot)


def forget_server_config(composite_key: str) -> bool:
    """Drop all checks for a server and persist.

    NOTE: this is NOT called on the normal server-removal sync path — a provider returning
    an erroneous empty list would then permanently erase a user's hand-built config. It is
    a deliberate, user-initiated "remove all checks for this server" action only.

    Args:
        composite_key: The server's composite key.

    Returns:
        bool: True if config existed and was removed and persisted; False if the load guard
            refused the operation, the server had no config, or the disk write failed. Memory
            is unchanged on guard/not-found failures and retains the removal when only the
            disk write fails.
    """
    with _write_lock:
        with _lock:
            _ensure_loaded()
            if _load_failed:
                logger.error("Not persisting config removal for %s: store file unreadable", composite_key)
                return False
            if composite_key not in _checks:
                return False
            del _checks[composite_key]
            snapshot = {key: list(cs) for key, cs in _checks.items()}
        return _persist(snapshot)
