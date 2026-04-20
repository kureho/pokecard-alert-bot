SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS events (
    id               TEXT PRIMARY KEY,
    source           TEXT NOT NULL,
    kind             TEXT NOT NULL,
    product_name     TEXT NOT NULL,
    product_raw      TEXT NOT NULL,
    normalized_key   TEXT NOT NULL,
    url              TEXT NOT NULL,
    detected_at      TIMESTAMP NOT NULL,
    source_ts        TIMESTAMP,
    price_yen        INTEGER,
    lottery_deadline TIMESTAMP,
    priority         INTEGER NOT NULL,
    extra_json       TEXT,
    notified_at      TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_events_normalized ON events(normalized_key, kind);
CREATE INDEX IF NOT EXISTS idx_events_detected ON events(detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_unnotified
    ON events(notified_at) WHERE notified_at IS NULL;

CREATE TABLE IF NOT EXISTS product_aliases (
    raw_title       TEXT NOT NULL,
    normalized_key  TEXT NOT NULL,
    source          TEXT NOT NULL,
    first_seen      TIMESTAMP NOT NULL,
    PRIMARY KEY (raw_title, source)
);

CREATE TABLE IF NOT EXISTS source_health (
    source                    TEXT PRIMARY KEY,
    last_success_at           TIMESTAMP,
    last_attempt_at           TIMESTAMP,
    last_nonzero_detection_at TIMESTAMP,
    consecutive_failures      INTEGER NOT NULL DEFAULT 0,
    last_error                TEXT
);

CREATE TABLE IF NOT EXISTS pending_aggregations (
    normalized_key  TEXT NOT NULL,
    event_id        TEXT NOT NULL,
    scheduled_at    TIMESTAMP NOT NULL,
    PRIMARY KEY (normalized_key, event_id)
);
"""
