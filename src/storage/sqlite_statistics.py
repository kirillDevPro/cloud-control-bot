"""SQLite repository for provider-scoped monitoring statistics."""

import sqlite3
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from contextlib import contextmanager

from ..exceptions import DatabaseError
from ..models.ping_result import PingResult, PingStatistics, PingStatus
from ..models.service_check import CheckStatus, ServiceCheckResult

logger = logging.getLogger(__name__)


class SqliteStatisticsRepository:
    """Store rolling ping statistics in SQLite with batching and corruption recovery.

    Rows are scoped by provider alias plus server ID so multi-account providers with the
    same bare server IDs never share statistics. The repository uses one cached SQLite
    connection protected by _db_lock, checkpoints WAL on close, and recreates the
    database only on confirmed SQLite file corruption. The retention window is
    configurable (default 30 days); at that size a rebuild is a real loss of history, so
    the rebuild trigger stays narrowly gated on a genuinely malformed file.
    """

    MAX_ERRORS_PER_SERVER = 100

    def __init__(self, db_path: Path, retention_days: int = 30):
        """
        Initialize the repository.

        Args:
            db_path: Path to the SQLite database file.
            retention_days: Rolling window in days after which aggregates and error
                rows are pruned. Must be positive.
        """
        self.db_path = db_path
        self._retention_hours = max(1, retention_days) * 24
        # Monotonic-clock time of the last prune per SUBSYSTEM, so each prune runs at
        # most once per hour independent of how many batches call it, and so a service-check
        # write never prunes — or rolls back on a failure pruning — the legacy ping tables and
        # vice-versa: each writer prunes ONLY its own tables (the parallel-table boundary).
        self._last_ping_prune_monotonic: float = 0.0
        self._last_check_prune_monotonic: float = 0.0
        self._connection: sqlite3.Connection | None = None
        # Guards lazy creation/close of the cached connection.
        self._connection_lock = threading.Lock()
        # Serializes ALL query execution: the single cached connection
        # (check_same_thread=False) is shared between the asyncio thread (reads)
        # and the to_thread batch writer, and one sqlite3 connection is not safe
        # for concurrent use. Distinct from _connection_lock to avoid re-entrancy.
        self._db_lock = threading.Lock()
        # Create the DB/tables and verify integrity; an unclean shutdown can leave a
        # WAL-mode DB malformed, so recreate the DB on confirmed corruption rather than
        # fail every write forever. At a 30-day window this discards real history, so
        # the trigger is gated on a genuinely malformed file (see _is_corruption_error).
        self._init_database()

    def _get_or_create_connection(self) -> sqlite3.Connection:
        """
        Return the existing connection or create a new one.

        Uses thread-safe lazy initialization to efficiently reuse a single
        connection. check_same_thread=False allows the connection to be used
        from different asyncio threads.

        Returns:
            sqlite3.Connection: The database connection.
        """
        if self._connection is None:
            with self._connection_lock:
                # Double-check locking
                if self._connection is None:
                    self._connection = sqlite3.connect(
                        str(self.db_path),
                        check_same_thread=False,  # For asyncio compatibility
                        timeout=30.0,  # Timeout when the database is locked
                    )
                    self._connection.row_factory = sqlite3.Row
                    # Enable WAL mode for better performance
                    self._connection.execute("PRAGMA journal_mode=WAL")
                    self._connection.execute("PRAGMA synchronous=NORMAL")
        return self._connection

    @contextmanager
    def _get_connection(self):
        """
        Context manager for working with a connection.

        Uses the cached connection for efficiency. Commits the transaction on
        success and rolls it back on any exception before re-raising.

        Yields:
            sqlite3.Connection: The active database connection.

        Raises:
            Exception: Re-raised after rolling back the transaction.
        """
        conn = self._get_or_create_connection()
        try:
            yield conn
            conn.commit()
        except Exception as e:
            logger.debug(f"Transaction rolled back due to error: {e}")
            conn.rollback()
            raise

    def close(self) -> None:
        """
        Checkpoint WAL and close the cached database connection.

        Called during application shutdown.
        """
        # Acquire _db_lock first (then _connection_lock) — the SAME lock order every
        # query path uses — so close() waits for any in-flight read/write to finish
        # instead of closing the connection out from under it.
        with self._db_lock, self._connection_lock:
            if self._connection is not None:
                # Checkpoint the WAL back into the main DB and truncate it, so the -wal
                # sidecar does not linger at its high-water mark across restarts.
                try:
                    self._connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                except Exception as e:
                    logger.debug(f"WAL checkpoint on close failed: {e}")
                try:
                    self._connection.close()
                except Exception as e:
                    logger.warning(f"Error closing SQLite connection: {e}", exc_info=True)
                finally:
                    self._connection = None

    @staticmethod
    def _is_corruption_error(error: Exception) -> bool:
        """Return True only for SQLite errors that mean the FILE is corrupt.

        Distinguishes genuine corruption (safe to delete + rebuild the disposable DB) from
        transient/operational errors — a locked DB, a permission/open failure, or a one-off
        I/O error (all sqlite3.OperationalError, a DatabaseError subclass) — which must NOT
        trigger the destructive rebuild of a possibly-valid database.

        Args:
            error: The exception raised by a SQLite call.

        Returns:
            bool: True if the message indicates a malformed/non-database/encrypted file.
        """
        msg = str(error).lower()
        return (
            "malformed" in msg
            or "not a database" in msg
            or "file is encrypted" in msg
            or "disk image is malformed" in msg
        )

    def _init_database(self) -> None:
        """Create the DB/tables and verify integrity, rebuilding the disposable DB if corrupt.

        Handles two corruption shapes after an unclean shutdown: a file SQLite cannot open at
        all (CREATE TABLE raises) and a file that opens but is logically malformed (caught by
        the quick_check in _verify_integrity_or_rebuild). A NON-corruption error (locked DB,
        permission, transient I/O) is logged but NEVER deletes the DB — degrading gracefully
        is far safer than destroying a possibly-valid database (and masking a stale process).
        """
        try:
            self._ensure_db_exists()
        except sqlite3.DatabaseError as e:
            if self._is_corruption_error(e):
                logger.critical(
                    f"Statistics DB is corrupt ({e}); rebuilding the database", exc_info=True
                )
                self._rebuild_database()
                return
            # Transient/operational error: do not destroy a possibly-valid DB. The repo's
            # per-query error handling degrades gracefully if the connection stays broken.
            logger.error(
                f"Statistics DB init error, NOT rebuilding ({e})", exc_info=True
            )
            return
        self._verify_integrity_or_rebuild()

    def _verify_integrity_or_rebuild(self) -> None:
        """Run a startup integrity check and rebuild the DB ONLY if it is genuinely corrupt.

        After an unclean shutdown a WAL-mode SQLite file can be left malformed, after which
        every write fails forever (throttled only by the emergency batch clear) with no
        signal. Recreating the DB is the only way to recover writes, so on a CONFIRMED
        malformed file it is deleted and recreated even though that discards the retention
        window of history. A transient/operational error (locked, permission) does NOT
        trigger the rebuild.
        """
        try:
            with self._db_lock, self._get_connection() as conn:
                row = conn.execute("PRAGMA quick_check").fetchone()
            result = row[0] if row else None
            if result == "ok":
                return
            logger.critical(
                f"Statistics DB integrity check failed ({result!r}); rebuilding the database"
            )
        except sqlite3.DatabaseError as e:
            if not self._is_corruption_error(e):
                # Locked/transient: do not destroy a possibly-valid DB.
                logger.error(
                    f"Statistics DB quick_check error, NOT rebuilding ({e})", exc_info=True
                )
                return
            logger.critical(
                f"Statistics DB is unreadable ({e}); rebuilding the database", exc_info=True
            )

        self._rebuild_database()

    def _rebuild_database(self) -> None:
        """Close and delete the statistics DB (plus its WAL/SHM sidecars), then recreate it."""
        self.close()
        for suffix in ("", "-wal", "-shm"):
            sidecar = Path(f"{self.db_path}{suffix}")
            try:
                sidecar.unlink(missing_ok=True)
            except Exception as e:
                logger.error(f"Failed to delete {sidecar} during rebuild: {e}", exc_info=True)
        self._ensure_db_exists()

    def _ensure_db_exists(self) -> None:
        """Create the database and tables if they do not exist."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        with self._get_connection() as conn:
            # PRAGMA settings are applied in _get_or_create_connection()

            # Create tables
            conn.executescript(
                """
                -- Table with hourly-aggregated statistics
                CREATE TABLE IF NOT EXISTS hourly_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server_id TEXT NOT NULL,
                    provider_type TEXT NOT NULL DEFAULT 'vultr',
                    hour_timestamp INTEGER NOT NULL,

                    -- Aggregates
                    total_pings INTEGER NOT NULL DEFAULT 0,
                    successful_pings INTEGER NOT NULL DEFAULT 0,
                    failed_pings INTEGER NOT NULL DEFAULT 0,
                    timeout_pings INTEGER NOT NULL DEFAULT 0,

                    -- Response time (for successful pings)
                    total_response_time_ms REAL DEFAULT 0.0,
                    min_response_time_ms REAL,
                    max_response_time_ms REAL,

                    -- Creation/update timestamp
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,

                    -- Uniqueness: one hour per server of a SPECIFIC provider
                    -- (provider_type is required in the key, otherwise two accounts with
                    --  the same server_id merge their statistics into one row)
                    UNIQUE(server_id, provider_type, hour_timestamp)
                );

                -- Indexes for fast lookups
                CREATE INDEX IF NOT EXISTS idx_hourly_stats_server_time
                    ON hourly_stats(server_id, provider_type, hour_timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_hourly_stats_timestamp
                    ON hourly_stats(hour_timestamp);

                -- Table of recent errors (only failed/timeout pings)
                CREATE TABLE IF NOT EXISTS ping_errors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server_id TEXT NOT NULL,
                    provider_type TEXT NOT NULL DEFAULT 'vultr',
                    timestamp INTEGER NOT NULL,

                    status TEXT NOT NULL CHECK(status IN ('failed', 'timeout')),
                    error TEXT,
                    packet_loss REAL NOT NULL DEFAULT 0.0,

                    -- New fields for status tracking
                    consecutive_failures INTEGER NOT NULL DEFAULT 0,
                    current_status TEXT NOT NULL DEFAULT 'unknown',
                    previous_status TEXT NOT NULL DEFAULT 'unknown',

                    -- Creation timestamp
                    created_at INTEGER NOT NULL
                );

                -- Indexes
                CREATE INDEX IF NOT EXISTS idx_ping_errors_server_time
                    ON ping_errors(server_id, provider_type, timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_ping_errors_timestamp
                    ON ping_errors(timestamp);

                -- ============================================================
                -- SERVICE CHECKS (TCP / HTTP / SSL) — PARALLEL tables.
                -- Deliberately separate from hourly_stats/ping_errors: there is no
                -- migration machinery here (schema is CREATE TABLE IF NOT EXISTS), so
                -- ALTERing a live table would diverge prod from dev invisibly and the
                -- first INSERT naming a missing column would re-queue and drop stats for
                -- every server. New tables are free; altering the old ones is not. New
                -- tables use the accurate 'provider_alias' column name (the ping tables'
                -- 'provider_type' actually holds an alias — a misnomer not copied here).
                -- ============================================================

                -- Hourly-aggregated service-check statistics, one row per check per hour.
                CREATE TABLE IF NOT EXISTS check_hourly_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server_id TEXT NOT NULL,
                    provider_alias TEXT NOT NULL,
                    check_id TEXT NOT NULL,
                    hour_timestamp INTEGER NOT NULL,

                    total_checks INTEGER NOT NULL DEFAULT 0,
                    successful_checks INTEGER NOT NULL DEFAULT 0,
                    failed_checks INTEGER NOT NULL DEFAULT 0,
                    timeout_checks INTEGER NOT NULL DEFAULT 0,

                    total_latency_ms REAL DEFAULT 0.0,
                    min_latency_ms REAL,
                    max_latency_ms REAL,

                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,

                    -- One hour per check of a specific server+provider.
                    UNIQUE(server_id, provider_alias, check_id, hour_timestamp)
                );

                CREATE INDEX IF NOT EXISTS idx_check_hourly_stats_lookup
                    ON check_hourly_stats(server_id, provider_alias, check_id, hour_timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_check_hourly_stats_timestamp
                    ON check_hourly_stats(hour_timestamp);

                -- Recent service-check errors. NOTE: status has NO CHECK constraint on
                -- purpose — service checks produce statuses ping_errors never will
                -- (assert_failed, cert_expiring, cert_invalid), SQLite cannot ALTER a
                -- CHECK constraint, and the ping_errors CHECK(status IN ...) is exactly
                -- what forecloses reusing that table. Do NOT add one back here.
                CREATE TABLE IF NOT EXISTS check_errors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server_id TEXT NOT NULL,
                    provider_alias TEXT NOT NULL,
                    check_id TEXT NOT NULL,
                    timestamp INTEGER NOT NULL,

                    status TEXT NOT NULL,
                    error TEXT,

                    created_at INTEGER NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_check_errors_lookup
                    ON check_errors(server_id, provider_alias, check_id, timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_check_errors_timestamp
                    ON check_errors(timestamp);

                -- Current SSL-certificate state: one row per SSL check (upserted), NOT an
                -- hourly aggregate — 'days until expiry' is a point-in-time scalar, not a
                -- rate to sum over an hour. Deliberately NOT pruned by the retention
                -- window (pruning it would blank the SSL card).
                CREATE TABLE IF NOT EXISTS check_ssl_state (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server_id TEXT NOT NULL,
                    provider_alias TEXT NOT NULL,
                    check_id TEXT NOT NULL,
                    checked_at INTEGER NOT NULL,
                    not_after_ts INTEGER,
                    days_left INTEGER,
                    status TEXT NOT NULL,
                    verify_error TEXT,

                    UNIQUE(server_id, provider_alias, check_id)
                );
            """
            )

    # === BATCHING ===

    def add_ping_batch(self, results: list[PingResult]) -> None:
        """
        Add a batch of ping results.

        Updates the aggregates in hourly_stats and appends error rows to
        ping_errors, then prunes data older than the retention window.

        Args:
            results: List of ping results to persist.

        Raises:
            DatabaseError: If the batch could not be written to SQLite.
        """
        if not results:
            return

        try:
            with self._db_lock, self._get_connection() as conn:
                for result in results:
                    # Determine the hour bucket
                    hour_ts = self._get_hour_timestamp(result.timestamp)

                    # Update the aggregates
                    self._update_hourly_stats(conn, result, hour_ts)

                    # Record an error row if needed
                    if result.status in (PingStatus.FAILED, PingStatus.TIMEOUT):
                        self._add_error(conn, result)

                # Prune old ping data (only — the check tables have their own prune)
                self._cleanup_ping_data(conn)

        except sqlite3.Error as e:
            logger.error(f"Failed to save batch: {e}", exc_info=True)
            raise DatabaseError(f"Failed to save the statistics batch: {e}") from e

    def _update_hourly_stats(
        self, conn: sqlite3.Connection, result: PingResult, hour_ts: int
    ) -> None:
        """
        Update the hourly aggregates for a single ping result.

        Inserts a new row for the hour bucket or updates the existing one,
        incrementing the per-status counters and recomputing the response-time
        totals (sum/min/max are only updated for successful pings).

        Args:
            conn: Active SQLite connection (within a transaction).
            result: The ping result to fold into the aggregates.
            hour_ts: Unix timestamp of the start of the result's hour bucket.
        """
        # Fetch the current aggregates if they exist
        row = conn.execute(
            """
            SELECT
                total_pings,
                successful_pings,
                failed_pings,
                timeout_pings,
                total_response_time_ms,
                min_response_time_ms,
                max_response_time_ms
            FROM hourly_stats
            WHERE server_id = ? AND provider_type = ? AND hour_timestamp = ?
            """,
            (result.server_id, result.provider_type, hour_ts),
        ).fetchone()

        now_ts = int(datetime.now().timestamp())

        if row:
            # Update the existing row
            total_pings = row["total_pings"] + 1
            successful_pings = row["successful_pings"] + (
                1 if result.status == PingStatus.SUCCESS else 0
            )
            failed_pings = row["failed_pings"] + (1 if result.status == PingStatus.FAILED else 0)
            timeout_pings = row["timeout_pings"] + (1 if result.status == PingStatus.TIMEOUT else 0)

            # Update response time (only for successful pings)
            if result.status == PingStatus.SUCCESS and result.response_time_ms is not None:
                total_response_time_ms = row["total_response_time_ms"] + result.response_time_ms
                min_response_time_ms = (
                    min(row["min_response_time_ms"], result.response_time_ms)
                    if row["min_response_time_ms"] is not None
                    else result.response_time_ms
                )
                max_response_time_ms = (
                    max(row["max_response_time_ms"], result.response_time_ms)
                    if row["max_response_time_ms"] is not None
                    else result.response_time_ms
                )
            else:
                total_response_time_ms = row["total_response_time_ms"]
                min_response_time_ms = row["min_response_time_ms"]
                max_response_time_ms = row["max_response_time_ms"]

            conn.execute(
                """
                UPDATE hourly_stats
                SET
                    total_pings = ?,
                    successful_pings = ?,
                    failed_pings = ?,
                    timeout_pings = ?,
                    total_response_time_ms = ?,
                    min_response_time_ms = ?,
                    max_response_time_ms = ?,
                    updated_at = ?
                WHERE server_id = ? AND provider_type = ? AND hour_timestamp = ?
                """,
                (
                    total_pings,
                    successful_pings,
                    failed_pings,
                    timeout_pings,
                    total_response_time_ms,
                    min_response_time_ms,
                    max_response_time_ms,
                    now_ts,
                    result.server_id,
                    result.provider_type,
                    hour_ts,
                ),
            )
        else:
            # Create a new row
            total_pings = 1
            successful_pings = 1 if result.status == PingStatus.SUCCESS else 0
            failed_pings = 1 if result.status == PingStatus.FAILED else 0
            timeout_pings = 1 if result.status == PingStatus.TIMEOUT else 0

            if result.status == PingStatus.SUCCESS and result.response_time_ms is not None:
                total_response_time_ms = result.response_time_ms
                min_response_time_ms = result.response_time_ms
                max_response_time_ms = result.response_time_ms
            else:
                total_response_time_ms = 0.0
                min_response_time_ms = None
                max_response_time_ms = None

            conn.execute(
                """
                INSERT INTO hourly_stats (
                    server_id,
                    provider_type,
                    hour_timestamp,
                    total_pings,
                    successful_pings,
                    failed_pings,
                    timeout_pings,
                    total_response_time_ms,
                    min_response_time_ms,
                    max_response_time_ms,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.server_id,
                    result.provider_type,
                    hour_ts,
                    total_pings,
                    successful_pings,
                    failed_pings,
                    timeout_pings,
                    total_response_time_ms,
                    min_response_time_ms,
                    max_response_time_ms,
                    now_ts,
                    now_ts,
                ),
            )

    def _add_error(self, conn: sqlite3.Connection, result: PingResult) -> None:
        """
        Insert a failed/timeout ping into the ping_errors table.

        After inserting, trims the server's error rows down to
        MAX_ERRORS_PER_SERVER.

        Args:
            conn: Active SQLite connection (within a transaction).
            result: The failed or timed-out ping result to record.
        """
        conn.execute(
            """
            INSERT INTO ping_errors
                (server_id, provider_type, timestamp, status, error, packet_loss,
                 consecutive_failures, current_status, previous_status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result.server_id,
                result.provider_type,
                int(result.timestamp.timestamp()),
                result.status.value,
                result.error,
                result.packet_loss,
                result.consecutive_failures,
                result.current_status,
                result.previous_status,
                int(datetime.now().timestamp()),
            ),
        )

        # Cap the number of stored errors
        self._limit_errors(conn, result.server_id, result.provider_type)

    def _limit_errors(self, conn: sqlite3.Connection, server_id: str, provider_type: str) -> None:
        """
        Delete the oldest errors beyond MAX_ERRORS_PER_SERVER for a server.

        Scoped by provider_type so trimming one account's errors never evicts the
        rows of a different account that shares the same bare server_id.

        Args:
            conn: Active SQLite connection (within a transaction).
            server_id: The server whose error rows should be trimmed.
            provider_type: The provider alias the rows belong to.
        """
        conn.execute(
            """
            DELETE FROM ping_errors
            WHERE id IN (
                SELECT id FROM ping_errors
                WHERE server_id = ? AND provider_type = ?
                ORDER BY timestamp DESC
                LIMIT -1 OFFSET ?
            )
            """,
            (server_id, provider_type, self.MAX_ERRORS_PER_SERVER),
        )

    # === SERVICE-CHECK BATCHING ===

    # Statuses that count as reachable/healthy for the hourly aggregates (CERT_EXPIRING is
    # a warning, not a failure — the endpoint is reachable and the cert is valid).
    _CHECK_SUCCESS_STATUSES = (CheckStatus.OK, CheckStatus.CERT_EXPIRING)
    # Non-OK statuses recorded as error rows (CERT_EXPIRING is surfaced via the SSL-state
    # table + its level-triggered alert, not as an error row).
    _CHECK_ERROR_STATUSES = (
        CheckStatus.FAILED,
        CheckStatus.TIMEOUT,
        CheckStatus.ASSERT_FAILED,
        CheckStatus.CERT_INVALID,
    )

    def add_check_batch(self, results: list[ServiceCheckResult]) -> None:
        """
        Add a batch of service-check results.

        Mirrors add_ping_batch: the whole batch is written in ONE transaction (rolled back
        wholesale on error) so a caller-side re-queue on failure cannot double-count. SSL
        results additionally upsert the current-state table. Afterwards it runs the
        independently time-gated service-check prune; ping tables are never touched here.

        Args:
            results: List of service-check results to persist.

        Returns:
            None.

        Raises:
            DatabaseError: If the batch could not be written to SQLite.
        """
        if not results:
            return

        try:
            with self._db_lock, self._get_connection() as conn:
                for result in results:
                    hour_ts = self._get_hour_timestamp(result.timestamp)
                    self._update_check_hourly_stats(conn, result, hour_ts)
                    if result.status in self._CHECK_ERROR_STATUSES:
                        self._add_check_error(conn, result)
                    if result.days_until_expiry is not None or result.not_after is not None:
                        self._upsert_ssl_state(conn, result)

                # Prune old check data (only — the ping tables have their own prune)
                self._cleanup_check_data(conn)

        except sqlite3.Error as e:
            logger.error(f"Failed to save check batch: {e}", exc_info=True)
            raise DatabaseError(f"Failed to save the service-check batch: {e}") from e

    def _update_check_hourly_stats(
        self, conn: sqlite3.Connection, result: ServiceCheckResult, hour_ts: int
    ) -> None:
        """
        Fold one service-check result into its hourly aggregate row.

        Inserts a new row for the check's hour bucket or updates the existing one,
        incrementing the per-status counters and (for successful checks) the latency
        totals. Mirrors _update_hourly_stats for the ping path.

        Args:
            conn: Active SQLite connection (within a transaction).
            result: The service-check result to fold in.
            hour_ts: Unix timestamp of the start of the result's hour bucket.

        Returns:
            None.
        """
        is_success = result.status in self._CHECK_SUCCESS_STATUSES
        is_timeout = result.status == CheckStatus.TIMEOUT
        is_failed = not is_success and not is_timeout
        has_latency = is_success and result.latency_ms is not None

        row = conn.execute(
            """
            SELECT total_checks, successful_checks, failed_checks, timeout_checks,
                   total_latency_ms, min_latency_ms, max_latency_ms
            FROM check_hourly_stats
            WHERE server_id = ? AND provider_alias = ? AND check_id = ? AND hour_timestamp = ?
            """,
            (result.server_id, result.provider_alias, result.check_id, hour_ts),
        ).fetchone()

        now_ts = int(datetime.now().timestamp())

        if row:
            total = row["total_checks"] + 1
            successful = row["successful_checks"] + (1 if is_success else 0)
            failed = row["failed_checks"] + (1 if is_failed else 0)
            timeout = row["timeout_checks"] + (1 if is_timeout else 0)
            if has_latency:
                total_latency = row["total_latency_ms"] + result.latency_ms
                min_latency = (
                    min(row["min_latency_ms"], result.latency_ms)
                    if row["min_latency_ms"] is not None
                    else result.latency_ms
                )
                max_latency = (
                    max(row["max_latency_ms"], result.latency_ms)
                    if row["max_latency_ms"] is not None
                    else result.latency_ms
                )
            else:
                total_latency = row["total_latency_ms"]
                min_latency = row["min_latency_ms"]
                max_latency = row["max_latency_ms"]

            conn.execute(
                """
                UPDATE check_hourly_stats
                SET total_checks = ?, successful_checks = ?, failed_checks = ?,
                    timeout_checks = ?, total_latency_ms = ?, min_latency_ms = ?,
                    max_latency_ms = ?, updated_at = ?
                WHERE server_id = ? AND provider_alias = ? AND check_id = ? AND hour_timestamp = ?
                """,
                (
                    total, successful, failed, timeout,
                    total_latency, min_latency, max_latency, now_ts,
                    result.server_id, result.provider_alias, result.check_id, hour_ts,
                ),
            )
        else:
            latency = result.latency_ms if has_latency else None
            conn.execute(
                """
                INSERT INTO check_hourly_stats (
                    server_id, provider_alias, check_id, hour_timestamp,
                    total_checks, successful_checks, failed_checks, timeout_checks,
                    total_latency_ms, min_latency_ms, max_latency_ms, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.server_id, result.provider_alias, result.check_id, hour_ts,
                    1,
                    1 if is_success else 0,
                    1 if is_failed else 0,
                    1 if is_timeout else 0,
                    latency if latency is not None else 0.0,
                    latency,
                    latency,
                    now_ts,
                    now_ts,
                ),
            )

    def _add_check_error(self, conn: sqlite3.Connection, result: ServiceCheckResult) -> None:
        """
        Insert a failed service-check into check_errors and trim per (server, check).

        Args:
            conn: Active SQLite connection (within a transaction).
            result: The failed service-check result to record.

        Returns:
            None.
        """
        conn.execute(
            """
            INSERT INTO check_errors
                (server_id, provider_alias, check_id, timestamp, status, error, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result.server_id,
                result.provider_alias,
                result.check_id,
                int(result.timestamp.timestamp()),
                result.status.value,
                result.error,
                int(datetime.now().timestamp()),
            ),
        )
        self._limit_check_errors(conn, result.server_id, result.provider_alias, result.check_id)

    def _limit_check_errors(
        self, conn: sqlite3.Connection, server_id: str, provider_alias: str, check_id: str
    ) -> None:
        """
        Trim a single check's error rows to MAX_ERRORS_PER_SERVER.

        Partitioned by check_id as well as server/provider, so a noisy HTTP check failing
        every cycle cannot evict a quiet TCP check's error history (each check keeps its
        own budget).

        Args:
            conn: Active SQLite connection (within a transaction).
            server_id: The server whose check errors are trimmed.
            provider_alias: The provider alias scoping the rows.
            check_id: The specific check whose rows are trimmed.

        Returns:
            None.
        """
        conn.execute(
            """
            DELETE FROM check_errors
            WHERE id IN (
                SELECT id FROM check_errors
                WHERE server_id = ? AND provider_alias = ? AND check_id = ?
                ORDER BY timestamp DESC
                LIMIT -1 OFFSET ?
            )
            """,
            (server_id, provider_alias, check_id, self.MAX_ERRORS_PER_SERVER),
        )

    def _upsert_ssl_state(self, conn: sqlite3.Connection, result: ServiceCheckResult) -> None:
        """
        Upsert the current SSL-certificate state for a check (one row per check).

        Args:
            conn: Active SQLite connection (within a transaction).
            result: An SSL service-check result carrying expiry/validity fields.

        Returns:
            None.
        """
        not_after_ts = int(result.not_after.timestamp()) if result.not_after is not None else None
        conn.execute(
            """
            INSERT INTO check_ssl_state
                (server_id, provider_alias, check_id, checked_at, not_after_ts,
                 days_left, status, verify_error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(server_id, provider_alias, check_id) DO UPDATE SET
                checked_at = excluded.checked_at,
                not_after_ts = excluded.not_after_ts,
                days_left = excluded.days_left,
                status = excluded.status,
                verify_error = excluded.verify_error
            """,
            (
                result.server_id,
                result.provider_alias,
                result.check_id,
                int(result.timestamp.timestamp()),
                not_after_ts,
                result.days_until_expiry,
                result.status.value,
                result.error,
            ),
        )

    # === READING AGGREGATES ===

    def get_recent_statistics(
        self, server_id: str, provider_type: str, hours: int = 24
    ) -> PingStatistics:
        """
        Compute aggregated statistics for a recent time window.

        Reads hourly_stats and sums the aggregates over the requested window.
        On SQLite error, returns an empty PingStatistics instead of raising.

        Args:
            server_id: ID of the server.
            provider_type: Provider alias scoping the rows (avoids cross-account
                collisions when two accounts share a bare server_id).
            hours: Size of the look-back window in hours.

        Returns:
            PingStatistics: Aggregated statistics for the window.
        """
        cutoff_ts = int((datetime.now() - timedelta(hours=hours)).timestamp())

        try:
            with self._db_lock, self._get_connection() as conn:
                row = conn.execute(
                    """
                    SELECT
                        SUM(total_pings) as total,
                        SUM(successful_pings) as successful,
                        SUM(failed_pings) as failed,
                        SUM(timeout_pings) as timeout,
                        SUM(total_response_time_ms) as total_response,
                        MIN(min_response_time_ms) as min_response,
                        MAX(max_response_time_ms) as max_response
                    FROM hourly_stats
                    WHERE server_id = ? AND provider_type = ? AND hour_timestamp >= ?
                    """,
                    (server_id, provider_type, cutoff_ts),
                ).fetchone()

                if not row or row["total"] is None or row["total"] == 0:
                    return PingStatistics(
                        server_id=server_id,
                        total_pings=0,
                        successful_pings=0,
                        failed_pings=0,
                        timeout_pings=0,
                        avg_response_time_ms=0.0,
                        min_response_time_ms=None,
                        max_response_time_ms=None,
                        uptime_percentage=100.0,
                        last_downtime=None,
                    )

                # Compute the average response time
                total = row["total"]
                successful = row["successful"]
                total_response = row["total_response"] or 0.0

                avg_response = (total_response / successful) if successful > 0 else 0.0
                uptime = (successful / total * 100.0) if total > 0 else 100.0

                # Get the most recent downtime from the error rows, bounded to the SAME
                # window as the aggregates so a stale error outside the window is not
                # reported as this window's last downtime.
                last_downtime = self._get_last_downtime(
                    conn, server_id, provider_type, hours
                )

                return PingStatistics(
                    server_id=server_id,
                    total_pings=total,
                    successful_pings=successful,
                    failed_pings=row["failed"] or 0,
                    timeout_pings=row["timeout"] or 0,
                    avg_response_time_ms=avg_response,
                    min_response_time_ms=row["min_response"],
                    max_response_time_ms=row["max_response"],
                    uptime_percentage=uptime,
                    last_downtime=last_downtime,
                )

        except sqlite3.Error as e:
            logger.error(f"Failed to get statistics for {server_id}: {e}", exc_info=True)
            # Return empty statistics on error
            return PingStatistics(
                server_id=server_id,
                total_pings=0,
                successful_pings=0,
                failed_pings=0,
                timeout_pings=0,
                avg_response_time_ms=0.0,
                min_response_time_ms=None,
                max_response_time_ms=None,
                uptime_percentage=100.0,
                last_downtime=None,
            )

    def _get_last_downtime(
        self, conn: sqlite3.Connection, server_id: str, provider_type: str, hours: int
    ) -> datetime | None:
        """
        Get the timestamp of the most recent downtime WITHIN the given window.

        The window bound is required: without it, at a 30-day retention this returns an
        outage from days ago and stamps it onto a "1h" statistics card. The prune used
        to bound this implicitly at 24h; it no longer does.

        Args:
            conn: Active SQLite connection.
            server_id: ID of the server.
            provider_type: Provider alias scoping the lookup.
            hours: Size of the look-back window in hours (the caller's window).

        Returns:
            datetime | None: UTC timestamp of the latest error inside the window, or
            None if the server has no error rows in it.
        """
        cutoff_ts = int((datetime.now() - timedelta(hours=hours)).timestamp())
        row = conn.execute(
            """
            SELECT timestamp FROM ping_errors
            WHERE server_id = ? AND provider_type = ? AND timestamp >= ?
            ORDER BY timestamp DESC
            LIMIT 1
            """,
            (server_id, provider_type, cutoff_ts),
        ).fetchone()

        if row:
            return datetime.fromtimestamp(row["timestamp"], tz=timezone.utc)
        return None

    def get_recent_errors(
        self, server_id: str, provider_type: str, limit: int = 100, hours: int | None = None
    ) -> list[PingResult]:
        """
        Get the most recent errors for a server within the retention window.

        The time bound keeps "recent problems" recent: without it, at a 30-day retention
        errors from weeks ago surface as current. The prune used to bound this implicitly
        at 24h; it no longer does. On SQLite error, returns an empty list instead of raising.

        Args:
            server_id: ID of the server.
            provider_type: Provider alias scoping the rows.
            limit: Maximum number of rows to return.
            hours: Only return errors newer than this many hours. None (the default) uses the
                configured retention window, so existing callers see every retained error even
                when retention is raised above 30 days.

        Returns:
            list[PingResult]: Errors ordered from newest to oldest.
        """
        window_hours = self._retention_hours if hours is None else hours
        cutoff_ts = int((datetime.now() - timedelta(hours=window_hours)).timestamp())
        try:
            with self._db_lock, self._get_connection() as conn:
                rows = conn.execute(
                    """
                    SELECT * FROM ping_errors
                    WHERE server_id = ? AND provider_type = ? AND timestamp >= ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (server_id, provider_type, cutoff_ts, limit),
                ).fetchall()

                results = []
                for row in rows:
                    # Use try/except for backward compatibility with older databases
                    try:
                        consecutive_failures = row["consecutive_failures"]
                    except (KeyError, IndexError):
                        consecutive_failures = 0

                    try:
                        current_status = row["current_status"]
                    except (KeyError, IndexError):
                        current_status = "unknown"

                    try:
                        previous_status = row["previous_status"]
                    except (KeyError, IndexError):
                        previous_status = "unknown"

                    results.append(
                        PingResult(
                            server_id=row["server_id"],
                            provider_type=row["provider_type"],
                            timestamp=datetime.fromtimestamp(row["timestamp"], tz=timezone.utc),
                            status=PingStatus(row["status"]),
                            error=row["error"],
                            packet_loss=row["packet_loss"],
                            response_time_ms=None,
                            consecutive_failures=consecutive_failures,
                            current_status=current_status,
                            previous_status=previous_status,
                        )
                    )

                return results

        except sqlite3.Error as e:
            logger.error(f"Failed to get errors for {server_id}: {e}", exc_info=True)
            return []

    # === READING SERVICE-CHECK AGGREGATES ===

    def get_check_statistics(
        self, server_id: str, provider_alias: str, hours: int = 24
    ) -> dict[str, dict]:
        """
        Aggregate service-check statistics per check over a recent window.

        Uses ONE GROUP BY query rather than a per-check loop, so rendering a server's
        checks does not multiply the dashboard's per-server query count (and its _db_lock
        contention with the batch writer) by the number of checks. On SQLite error,
        returns an empty mapping instead of raising.

        Args:
            server_id: ID of the server.
            provider_alias: Provider alias scoping the rows.
            hours: Size of the look-back window in hours.

        Returns:
            dict[str, dict]: Mapping of check_id to its aggregates
                (total/successful/failed/timeout, uptime_percentage, avg/min/max latency).
        """
        cutoff_ts = int((datetime.now() - timedelta(hours=hours)).timestamp())
        try:
            with self._db_lock, self._get_connection() as conn:
                rows = conn.execute(
                    """
                    SELECT
                        check_id,
                        SUM(total_checks) AS total,
                        SUM(successful_checks) AS successful,
                        SUM(failed_checks) AS failed,
                        SUM(timeout_checks) AS timeout,
                        SUM(total_latency_ms) AS total_latency,
                        MIN(min_latency_ms) AS min_latency,
                        MAX(max_latency_ms) AS max_latency
                    FROM check_hourly_stats
                    WHERE server_id = ? AND provider_alias = ? AND hour_timestamp >= ?
                    GROUP BY check_id
                    """,
                    (server_id, provider_alias, cutoff_ts),
                ).fetchall()

                stats: dict[str, dict] = {}
                for row in rows:
                    total = row["total"] or 0
                    successful = row["successful"] or 0
                    total_latency = row["total_latency"] or 0.0
                    stats[row["check_id"]] = {
                        "total_checks": total,
                        "successful_checks": successful,
                        "failed_checks": row["failed"] or 0,
                        "timeout_checks": row["timeout"] or 0,
                        "uptime_percentage": (successful / total * 100.0) if total > 0 else 100.0,
                        "avg_latency_ms": (total_latency / successful) if successful > 0 else 0.0,
                        "min_latency_ms": row["min_latency"],
                        "max_latency_ms": row["max_latency"],
                    }
                return stats

        except sqlite3.Error as e:
            logger.error(f"Failed to get check statistics for {server_id}: {e}", exc_info=True)
            return {}

    def get_ssl_state(
        self, server_id: str, provider_alias: str, check_id: str
    ) -> dict | None:
        """
        Return the current SSL-certificate state for a check, or None when unknown.

        On SQLite error, returns None instead of raising.

        Args:
            server_id: ID of the server.
            provider_alias: Provider alias scoping the row.
            check_id: The SSL check to read.

        Returns:
            dict | None: Mapping with checked_at, not_after (datetime|None), days_left,
                status, verify_error — or None when the check has never run.
        """
        try:
            with self._db_lock, self._get_connection() as conn:
                row = conn.execute(
                    """
                    SELECT checked_at, not_after_ts, days_left, status, verify_error
                    FROM check_ssl_state
                    WHERE server_id = ? AND provider_alias = ? AND check_id = ?
                    """,
                    (server_id, provider_alias, check_id),
                ).fetchone()

                if not row:
                    return None
                not_after = (
                    datetime.fromtimestamp(row["not_after_ts"], tz=timezone.utc)
                    if row["not_after_ts"] is not None
                    else None
                )
                return {
                    "checked_at": datetime.fromtimestamp(row["checked_at"], tz=timezone.utc),
                    "not_after": not_after,
                    "days_left": row["days_left"],
                    "status": row["status"],
                    "verify_error": row["verify_error"],
                }

        except sqlite3.Error as e:
            logger.error(f"Failed to get SSL state for {server_id}: {e}", exc_info=True)
            return None

    def delete_check_state(self, server_id: str, provider_alias: str, check_id: str) -> bool:
        """
        Delete all stored state for a single check (history + errors + SSL state).

        Called when an admin deletes a check, so its rows do not linger. On SQLite error,
        returns False instead of raising.

        Args:
            server_id: ID of the server.
            provider_alias: Provider alias scoping the rows.
            check_id: The check whose stored state is removed.

        Returns:
            bool: True on success, False on SQLite error.
        """
        try:
            with self._db_lock, self._get_connection() as conn:
                conn.execute(
                    "DELETE FROM check_hourly_stats "
                    "WHERE server_id = ? AND provider_alias = ? AND check_id = ?",
                    (server_id, provider_alias, check_id),
                )
                conn.execute(
                    "DELETE FROM check_errors "
                    "WHERE server_id = ? AND provider_alias = ? AND check_id = ?",
                    (server_id, provider_alias, check_id),
                )
                conn.execute(
                    "DELETE FROM check_ssl_state "
                    "WHERE server_id = ? AND provider_alias = ? AND check_id = ?",
                    (server_id, provider_alias, check_id),
                )
                return True
        except sqlite3.Error as e:
            logger.error(f"Failed to delete check state for {server_id}: {e}", exc_info=True)
            return False

    # === CLEANUP ===

    def _cleanup_ping_data(self, conn: sqlite3.Connection) -> None:
        """
        Delete ping aggregates/errors older than the retention window, at most once per hour.

        Time-gated (per subsystem) so add_ping_batch's prune frequency is independent of the
        number of batch writers, and so a service-check write never touches — or rolls back
        on a failure pruning — these legacy tables. The DELETEs are index-supported, so the
        gate is about lock-hold frequency, not scan cost.

        Args:
            conn: Active SQLite connection (within a transaction).

        Returns:
            None.
        """
        now_monotonic = time.monotonic()
        if now_monotonic - self._last_ping_prune_monotonic < 3600.0:
            return
        cutoff_ts = int((datetime.now() - timedelta(hours=self._retention_hours)).timestamp())
        conn.execute("DELETE FROM hourly_stats WHERE hour_timestamp < ?", (cutoff_ts,))
        conn.execute("DELETE FROM ping_errors WHERE timestamp < ?", (cutoff_ts,))
        # Advance the gate only after the DELETEs so a failed prune retries on the next batch.
        self._last_ping_prune_monotonic = now_monotonic

    def _cleanup_check_data(self, conn: sqlite3.Connection) -> None:
        """
        Delete service-check aggregates/errors older than the retention window, once per hour.

        Separate from the ping prune (the parallel-table boundary): add_check_batch touches
        ONLY the check_* tables. check_ssl_state is deliberately NOT pruned — it is
        current-state (one row per check), and pruning it would blank the SSL card between the
        widely-spaced SSL checks.

        Args:
            conn: Active SQLite connection (within a transaction).

        Returns:
            None.
        """
        now_monotonic = time.monotonic()
        if now_monotonic - self._last_check_prune_monotonic < 3600.0:
            return
        cutoff_ts = int((datetime.now() - timedelta(hours=self._retention_hours)).timestamp())
        conn.execute("DELETE FROM check_hourly_stats WHERE hour_timestamp < ?", (cutoff_ts,))
        conn.execute("DELETE FROM check_errors WHERE timestamp < ?", (cutoff_ts,))
        # Advance the gate only after the DELETEs so a failed prune retries on the next batch.
        self._last_check_prune_monotonic = now_monotonic

    def clear_server_history(self, server_key: str) -> bool:
        """
        Delete all history for a server.

        Accepts both a plain server_id and a composite_key of the form
        "provider:server_id". On SQLite error, returns False instead of raising.

        Args:
            server_key: A server ID, or a composite_key of the form
                "provider:server_id".

        Returns:
            bool: True if the history was deleted, False on error.
        """
        try:
            # Parse the composite_key if given in "provider:server_id" form
            if ":" in server_key:
                provider_type, server_id = server_key.split(":", 1)
            else:
                # Legacy format - server_id only (for backward compatibility)
                server_id = server_key
                provider_type = None

            with self._db_lock, self._get_connection() as conn:
                if provider_type:
                    # Delete rows only for the specific provider. The ping tables key on
                    # provider_type (an alias); the check tables key on provider_alias —
                    # same value, different column name.
                    conn.execute(
                        "DELETE FROM hourly_stats WHERE server_id = ? AND provider_type = ?",
                        (server_id, provider_type),
                    )
                    conn.execute(
                        "DELETE FROM ping_errors WHERE server_id = ? AND provider_type = ?",
                        (server_id, provider_type),
                    )
                    conn.execute(
                        "DELETE FROM check_hourly_stats WHERE server_id = ? AND provider_alias = ?",
                        (server_id, provider_type),
                    )
                    conn.execute(
                        "DELETE FROM check_errors WHERE server_id = ? AND provider_alias = ?",
                        (server_id, provider_type),
                    )
                    conn.execute(
                        "DELETE FROM check_ssl_state WHERE server_id = ? AND provider_alias = ?",
                        (server_id, provider_type),
                    )
                else:
                    # Legacy behavior - delete by server_id (all providers)
                    conn.execute("DELETE FROM hourly_stats WHERE server_id = ?", (server_id,))
                    conn.execute("DELETE FROM ping_errors WHERE server_id = ?", (server_id,))
                    conn.execute("DELETE FROM check_hourly_stats WHERE server_id = ?", (server_id,))
                    conn.execute("DELETE FROM check_errors WHERE server_id = ?", (server_id,))
                    conn.execute("DELETE FROM check_ssl_state WHERE server_id = ?", (server_id,))

                return True
        except sqlite3.Error as e:
            logger.error(f"Failed to clear history for {server_key}: {e}", exc_info=True)
            return False

    # === UTILITIES ===

    @staticmethod
    def _get_hour_timestamp(dt: datetime) -> int:
        """
        Return the Unix timestamp of the start of the hour.

        Args:
            dt: The datetime to truncate to the start of its hour.

        Returns:
            int: Unix timestamp of the hour boundary.
        """
        hour_start = dt.replace(minute=0, second=0, microsecond=0)
        return int(hour_start.timestamp())
