-- kabu-relay SQLite schema
-- All timestamps stored as ISO8601 UTC strings unless otherwise noted.

CREATE TABLE IF NOT EXISTS collector_runs (
    run_id      TEXT PRIMARY KEY,
    started_at  TEXT NOT NULL,
    config_path TEXT NOT NULL,
    db_path     TEXT NOT NULL,
    status      TEXT NOT NULL,    -- running | completed | failed
    notes       TEXT
);

CREATE TABLE IF NOT EXISTS orderbook_snapshots (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              TEXT    NOT NULL,
    collected_at        TEXT    NOT NULL,
    symbol              TEXT    NOT NULL,
    symbol_name         TEXT,
    bucket              TEXT,
    exchange            INTEGER,
    api_symbol          TEXT,
    best_bid_price      REAL,
    best_bid_qty        REAL,
    best_ask_price      REAL,
    best_ask_qty        REAL,
    mid_price           REAL,
    spread              REAL,
    spread_pct          REAL,
    bid_depth_5_jpy     REAL,
    ask_depth_5_jpy     REAL,
    bids_json           TEXT,
    asks_json           TEXT,
    trading_volume      REAL,
    vwap                REAL,
    current_price       REAL,
    current_price_time  TEXT,
    raw_json            TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_snapshots_symbol_collected_at
    ON orderbook_snapshots(symbol, collected_at);
CREATE INDEX IF NOT EXISTS idx_snapshots_api_symbol_collected_at
    ON orderbook_snapshots(api_symbol, collected_at);

CREATE TABLE IF NOT EXISTS price_changes (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id                  TEXT    NOT NULL,
    detected_at             TEXT    NOT NULL,
    symbol                  TEXT    NOT NULL,
    api_symbol              TEXT,
    change_type             TEXT    NOT NULL,
    prev_best_bid           REAL,
    prev_best_ask           REAL,
    new_best_bid            REAL,
    new_best_ask            REAL,
    prev_spread_pct         REAL,
    new_spread_pct          REAL,
    best_bid_duration_sec   REAL,
    best_ask_duration_sec   REAL
);

CREATE INDEX IF NOT EXISTS idx_price_changes_symbol_detected
    ON price_changes(symbol, detected_at);
CREATE INDEX IF NOT EXISTS idx_price_changes_api_symbol_detected
    ON price_changes(api_symbol, detected_at);

CREATE TABLE IF NOT EXISTS api_errors (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at TEXT NOT NULL,
    component   TEXT NOT NULL,
    symbol      TEXT,
    error_type  TEXT,
    message     TEXT,
    retryable   INTEGER
);

CREATE TABLE IF NOT EXISTS exports (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at              TEXT NOT NULL,
    file_path               TEXT NOT NULL,
    file_size_bytes         INTEGER,
    snapshot_rows           INTEGER,
    price_change_rows       INTEGER,
    latest_snapshot_at      TEXT
);
