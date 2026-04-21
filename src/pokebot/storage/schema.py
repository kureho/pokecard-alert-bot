SCHEMA_SQL = """
-- Phase 1 migration (2026-04-20): drop legacy tables
DROP TABLE IF EXISTS events CASCADE;
DROP TABLE IF EXISTS source_health CASCADE;
DROP TABLE IF EXISTS pending_aggregations CASCADE;
DROP TABLE IF EXISTS daily_reports CASCADE;
DROP TABLE IF EXISTS product_aliases CASCADE;

-- New Phase 1 schema
CREATE TABLE IF NOT EXISTS products (
    id                  BIGSERIAL PRIMARY KEY,
    canonical_name      TEXT NOT NULL,
    normalized_name     TEXT NOT NULL,
    release_date        DATE,
    product_type        TEXT,
    official_product_url TEXT,
    official_news_url   TEXT,
    created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (normalized_name)
);

CREATE TABLE IF NOT EXISTS product_aliases (
    id              BIGSERIAL PRIMARY KEY,
    product_id      BIGINT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    alias           TEXT NOT NULL,
    normalized_alias TEXT NOT NULL,
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (product_id, normalized_alias)
);
CREATE INDEX IF NOT EXISTS idx_product_aliases_normalized ON product_aliases(normalized_alias);

CREATE TABLE IF NOT EXISTS sources (
    id              BIGSERIAL PRIMARY KEY,
    source_name     TEXT NOT NULL UNIQUE,
    source_type     TEXT NOT NULL,  -- official_product, official_news, official_lottery, official_store_notice, retailer_lottery, retailer_notice, aggregator, social
    base_url        TEXT NOT NULL,
    trust_score     INTEGER NOT NULL DEFAULT 50,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    last_success_at TIMESTAMP,
    last_attempt_at TIMESTAMP,
    last_error      TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS lottery_events (
    id                              BIGSERIAL PRIMARY KEY,
    product_id                      BIGINT REFERENCES products(id) ON DELETE SET NULL,
    retailer_name                   TEXT NOT NULL,
    store_name                      TEXT,
    canonical_title                 TEXT NOT NULL,
    sales_type                      TEXT NOT NULL,  -- lottery, preorder_lottery, invitation, first_come, numbered_ticket, unknown
    apply_start_at                  TIMESTAMP,
    apply_end_at                    TIMESTAMP,
    result_at                       TIMESTAMP,
    purchase_start_at               TIMESTAMP,
    purchase_end_at                 TIMESTAMP,
    purchase_limit_text             TEXT,
    conditions_text                 TEXT,
    source_primary_url              TEXT,
    official_confirmation_status    TEXT NOT NULL DEFAULT 'unconfirmed',  -- confirmed, unconfirmed, conflicting
    confidence_score                INTEGER NOT NULL DEFAULT 0,
    dedupe_key                      TEXT NOT NULL UNIQUE,
    status                          TEXT NOT NULL DEFAULT 'active',  -- active, ended, cancelled, updated
    product_name_normalized         TEXT,
    first_seen_at                   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at                    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at                      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at                      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_lottery_events_product ON lottery_events(product_id);
CREATE INDEX IF NOT EXISTS idx_lottery_events_status ON lottery_events(status);
CREATE INDEX IF NOT EXISTS idx_lottery_events_apply_start ON lottery_events(apply_start_at);

-- 2026-04-21: product_name_normalized 列追加 (冪等)。既存 event は NULL のまま、
-- 新規 event から記録。クロスソース corroboration で使用する。
-- ALTER は CREATE INDEX より先に実行する必要あり (既存 DB で列が未作成のまま
-- index 定義にぶつかるのを避ける)。
ALTER TABLE lottery_events ADD COLUMN IF NOT EXISTS product_name_normalized TEXT;
CREATE INDEX IF NOT EXISTS idx_lottery_events_product_name
    ON lottery_events(product_name_normalized);

CREATE TABLE IF NOT EXISTS lottery_event_sources (
    id                      BIGSERIAL PRIMARY KEY,
    lottery_event_id        BIGINT NOT NULL REFERENCES lottery_events(id) ON DELETE CASCADE,
    source_id               BIGINT NOT NULL REFERENCES sources(id),
    source_url              TEXT NOT NULL,
    source_title            TEXT,
    source_published_at     TIMESTAMP,
    fetched_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    raw_snapshot_hash       TEXT NOT NULL,
    extracted_payload_json  JSONB,
    created_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (lottery_event_id, source_id, raw_snapshot_hash)
);
CREATE INDEX IF NOT EXISTS idx_les_event ON lottery_event_sources(lottery_event_id);

CREATE TABLE IF NOT EXISTS notifications (
    id                  BIGSERIAL PRIMARY KEY,
    lottery_event_id    BIGINT NOT NULL REFERENCES lottery_events(id) ON DELETE CASCADE,
    notification_type   TEXT NOT NULL,  -- new, update, deadline, result
    channel             TEXT NOT NULL DEFAULT 'line',
    dedupe_key          TEXT NOT NULL UNIQUE,
    payload_summary     TEXT,
    sent_at             TIMESTAMP,
    created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_notifications_event ON notifications(lottery_event_id);
CREATE INDEX IF NOT EXISTS idx_notifications_sent ON notifications(sent_at);

-- 2026-04-21: 精度向上前に作成された sales_type='unknown' な active event を
-- 新ロジックに合わせて pending_review へ retroactive migration。冪等。
UPDATE lottery_events SET status = 'pending_review'
WHERE status = 'active' AND sales_type = 'unknown';

-- 2026-04-21: daily_summary 通知のため lottery_event_id を nullable に。
-- 既に NULL 許可されている場合は no-op。
ALTER TABLE notifications ALTER COLUMN lottery_event_id DROP NOT NULL;

-- 2026-04-21: first-run seed の notification_type を 'seed' に分離 (冪等)。
UPDATE notifications SET notification_type = 'seed'
WHERE payload_summary = '[first-run seed; not sent]' AND notification_type <> 'seed';
-- seed 通知の sent_at も NULL に。
UPDATE notifications SET sent_at = NULL
WHERE notification_type = 'seed' AND sent_at IS NOT NULL;

-- 2026-04-21 07:00 cutoff: DRY_RUN で sent_at マークされていた new/update 通知を
-- 1 度だけ clear。以降は notifier が DryRunNotifier なら mark_sent をスキップする
-- ように修正済なので再発なし。time cutoff で冪等。
UPDATE notifications SET sent_at = NULL
WHERE sent_at IS NOT NULL
  AND sent_at < TIMESTAMP '2026-04-21 07:00:00'
  AND notification_type IN ('new', 'update');

-- 2026-04-21 07:15 cutoff: DRY_RUN で try_claim された空予約 (sent_at IS NULL) を削除。
-- DRY_RUN は dedupe に触れない実装に変更済みなので、1 度の clear で以降は発生しない。
-- cutoff 時刻で冪等。seed type は payload_summary 判定なので除外済。
DELETE FROM notifications
WHERE sent_at IS NULL
  AND notification_type IN ('new', 'update')
  AND created_at < TIMESTAMP '2026-04-21 07:15:00';
"""
