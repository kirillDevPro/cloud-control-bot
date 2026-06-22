"""
Utility for automatically cleaning up old, ROTATED log files.

Periodically scans the logs directory for rotated backups (``*.log.YYYY-MM-DD``)
older than a given number of days and deletes them, plus removes empty provider
subdirectories. The ACTIVE base files (``*.log``) are never touched — they are
held open by the rotating handlers and pruned via backupCount.
"""
import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

from .logger import LOG_RETENTION_DAYS

logger = logging.getLogger(__name__)

# Constants — retention is owned by logger.LOG_RETENTION_DAYS (single source of
# truth). The handler's backupCount prunes a worker's OWN rotated files; this task
# additionally sweeps ORPHANED rotated logs (e.g. of removed workers) and empty dirs.
DEFAULT_MAX_AGE_DAYS = LOG_RETENTION_DAYS  # Keep logs for the same window
CLEANUP_INTERVAL_HOURS = 24  # Check once a day


async def cleanup_old_logs(
    logs_dir: Path | str,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    dry_run: bool = False,
) -> int:
    """
    Delete rotated log backups (``*.log.YYYY-MM-DD``) older than the given age.

    The active base files (``*.log``) are intentionally excluded — they are still
    open in the rotating handlers.

    Args:
        logs_dir: Path to the logs directory
        max_age_days: Maximum file age in days (default: LOG_RETENTION_DAYS)
        dry_run: If True, only report what would be deleted without actually deleting

    Returns:
        Number of files deleted (or that would be deleted in dry-run mode)
    """
    logs_path = Path(logs_dir)

    if not logs_path.exists():
        logger.warning(f"Logs directory does not exist: {logs_path}")
        return 0

    # Compute the cutoff date
    cutoff_date = datetime.now() - timedelta(days=max_age_days)
    deleted_count = 0
    total_size_bytes = 0

    try:
        # Walk ROTATED backups only (e.g. main.log.2026-06-20). The active base
        # files (main.log, worker_*.log) match "*.log" but NOT "*.log.*", so they
        # are excluded — deleting a file an open handler still writes to would lose
        # log lines (POSIX) or fail (Windows).
        for log_file in logs_path.rglob("*.log.*"):
            try:
                # Read the file's modification time
                file_mtime = datetime.fromtimestamp(log_file.stat().st_mtime)

                # If the file is older than cutoff_date
                if file_mtime < cutoff_date:
                    file_size = log_file.stat().st_size
                    total_size_bytes += file_size

                    if dry_run:
                        logger.info(
                            f"[DRY RUN] Would delete: {log_file.relative_to(logs_path)} "
                            f"(age: {(datetime.now() - file_mtime).days} days, "
                            f"size: {file_size / 1024:.2f} KB)"
                        )
                    else:
                        logger.info(
                            f"Deleting old log: {log_file.relative_to(logs_path)} "
                            f"(age: {(datetime.now() - file_mtime).days} days, "
                            f"size: {file_size / 1024:.2f} KB)"
                        )
                        log_file.unlink()

                    deleted_count += 1

            except Exception as e:
                logger.error(f"Error processing file {log_file}: {e}", exc_info=True)
                continue

        # Remove empty provider directories
        if not dry_run:
            await _cleanup_empty_dirs(logs_path)

        if deleted_count > 0:
            action = "would delete" if dry_run else "deleted"
            logger.info(
                f"Log cleanup finished: {action} {deleted_count} file(s), "
                f"freed {total_size_bytes / 1024 / 1024:.2f} MB"
            )

    except Exception as e:
        logger.error(f"Error during log cleanup: {e}", exc_info=True)

    return deleted_count


async def _cleanup_empty_dirs(logs_dir: Path) -> None:
    """
    Remove empty provider/alias subdirectories inside the logs directory.

    Args:
        logs_dir: Path to the logs directory
    """
    try:
        for subdir in logs_dir.iterdir():
            # Only consider directories (not files)
            if subdir.is_dir():
                # Check whether the directory is empty
                if not any(subdir.iterdir()):
                    logger.info(f"Deleting empty directory: {subdir.relative_to(logs_dir)}")
                    subdir.rmdir()
    except Exception as e:
        logger.error(f"Error removing empty directories: {e}", exc_info=True)


async def log_cleanup_task(
    logs_dir: Path | str,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    interval_hours: int = CLEANUP_INTERVAL_HOURS,
    heartbeat: Callable[[], None] = lambda: None,
) -> None:
    """
    Background task that periodically deletes old rotated log backups.

    Runs cleanup_old_logs at the given interval. The first run happens immediately on
    startup, after an initial heartbeat so the supervisor does not flag the task as stale
    while cleanup is running.

    Args:
        logs_dir: Path to the logs directory
        max_age_days: Maximum file age in days
        interval_hours: Interval between checks, in hours
        heartbeat: Called once per loop iteration so the supervisor can detect a stall.
            Defaults to a no-op for standalone use/tests.

    Raises:
        asyncio.CancelledError: Re-raised when the task is cancelled (e.g. on shutdown)
        Exception: Re-raised on any unexpected fatal error in the loop
    """
    logger.info(
        f"Log cleanup background task started: "
        f"checking every {interval_hours} h, deleting files older than {max_age_days} days"
    )

    # Beat before the (possibly slow) initial cleanup so the supervisor never sees this
    # task as "started but never beaten" (matches the beat-before-work invariant of the
    # other tasks, which beat at the top of their loop).
    heartbeat()

    # First run immediately on startup
    await cleanup_old_logs(logs_dir, max_age_days)

    try:
        while True:
            heartbeat()  # progress beat at the top of every loop iteration
            # Wait for the configured interval
            await asyncio.sleep(interval_hours * 3600)

            # Perform the cleanup
            await cleanup_old_logs(logs_dir, max_age_days)

    except asyncio.CancelledError:
        logger.info("Log cleanup background task stopped")
        raise
    except Exception as e:
        logger.error(f"Critical error in the log cleanup task: {e}", exc_info=True)
        raise
