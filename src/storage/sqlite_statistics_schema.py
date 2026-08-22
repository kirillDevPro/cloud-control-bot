"""SQLite schema for provider-scoped monitoring statistics."""

SQLITE_STATISTICS_SCHEMA = """
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

                -- Tombstones for removed servers. A server dropped by servers_sync is
                -- recorded here instead of having its history deleted on the spot: a
                -- provider API that returns a truncated list would otherwise vaporize
                -- real history, and the same servers reappear minutes later. The rows are
                -- purged (together with the server's statistics) only after the grace
                -- window; a server that comes back before then has its tombstone removed
                -- and keeps every hour of history.
                CREATE TABLE IF NOT EXISTS deleted_servers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server_id TEXT NOT NULL,
                    provider_alias TEXT NOT NULL,
                    deleted_at INTEGER NOT NULL,

                    UNIQUE(server_id, provider_alias)
                );

                CREATE INDEX IF NOT EXISTS idx_deleted_servers_deleted_at
                    ON deleted_servers(deleted_at);
            """
