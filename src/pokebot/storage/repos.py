from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from .db import Database


@dataclass
class Product:
    id: int
    canonical_name: str
    normalized_name: str
    release_date: date | None
    product_type: str | None
    official_product_url: str | None
    official_news_url: str | None


@dataclass
class Source:
    id: int
    source_name: str
    source_type: str
    base_url: str
    trust_score: int
    is_active: bool
    last_success_at: datetime | None = None
    last_attempt_at: datetime | None = None
    consecutive_failures: int = 0
    last_error: str | None = None


@dataclass
class LotteryEvent:
    id: int
    product_id: int | None
    retailer_name: str
    store_name: str | None
    canonical_title: str
    sales_type: str
    apply_start_at: datetime | None
    apply_end_at: datetime | None
    result_at: datetime | None
    purchase_start_at: datetime | None
    purchase_end_at: datetime | None
    purchase_limit_text: str | None
    conditions_text: str | None
    source_primary_url: str | None
    official_confirmation_status: str
    confidence_score: int
    dedupe_key: str
    status: str
    first_seen_at: datetime
    last_seen_at: datetime
    product_name_normalized: str | None = None
    # Dispatch1: evidence 層 (全 nullable / default)。
    # 既存 active event は全て None/'unknown' のまま、次回 upsert 時に段階的に enrich。
    application_url: str | None = None
    product_url: str | None = None
    entry_method: str = "unknown"
    sale_status: str = "unknown"
    page_fingerprint: str | None = None
    evidence_score: int | None = None
    evidence_summary: str | None = None
    retailer_event_id: str | None = None
    confidence_level: str | None = None
    # retailer/store 非依存の content dedupe key。同一商品・同一応募期間・
    # 同一 sales_type なら、異なる retailer の告知も 1 event に統合される。
    content_dedupe_key: str | None = None


class ProductRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def upsert(
        self,
        *,
        canonical_name: str,
        normalized_name: str,
        release_date: date | None = None,
        product_type: str | None = None,
        official_product_url: str | None = None,
        official_news_url: str | None = None,
    ) -> int:
        """Return product id. Create if new, update if existing by normalized_name."""
        async with self._db.pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO products (canonical_name, normalized_name, release_date,
                       product_type, official_product_url, official_news_url)
                   VALUES ($1, $2, $3, $4, $5, $6)
                   ON CONFLICT (normalized_name) DO UPDATE SET
                       canonical_name = COALESCE(EXCLUDED.canonical_name, products.canonical_name),
                       release_date = COALESCE(EXCLUDED.release_date, products.release_date),
                       product_type = COALESCE(EXCLUDED.product_type, products.product_type),
                       official_product_url = COALESCE(EXCLUDED.official_product_url, products.official_product_url),
                       official_news_url = COALESCE(EXCLUDED.official_news_url, products.official_news_url),
                       updated_at = CURRENT_TIMESTAMP
                   RETURNING id""",
                canonical_name, normalized_name, release_date,
                product_type, official_product_url, official_news_url,
            )
        return row["id"]

    async def add_alias(self, product_id: int, alias: str, normalized_alias: str) -> None:
        async with self._db.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO product_aliases (product_id, alias, normalized_alias)
                   VALUES ($1, $2, $3) ON CONFLICT (product_id, normalized_alias) DO NOTHING""",
                product_id, alias, normalized_alias,
            )

    async def find_by_normalized(self, normalized_name: str) -> Product | None:
        async with self._db.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM products WHERE normalized_name = $1", normalized_name
            )
            if not row:
                # Check aliases
                row = await conn.fetchrow(
                    """SELECT p.* FROM products p
                       JOIN product_aliases a ON a.product_id = p.id
                       WHERE a.normalized_alias = $1 LIMIT 1""",
                    normalized_name,
                )
            if not row:
                return None
            return Product(
                id=row["id"], canonical_name=row["canonical_name"],
                normalized_name=row["normalized_name"],
                release_date=row["release_date"], product_type=row["product_type"],
                official_product_url=row["official_product_url"],
                official_news_url=row["official_news_url"],
            )

    async def list_all(self, limit: int = 200) -> list[Product]:
        async with self._db.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM products ORDER BY release_date DESC NULLS LAST, id DESC LIMIT $1",
                limit,
            )
        return [
            Product(
                id=r["id"], canonical_name=r["canonical_name"],
                normalized_name=r["normalized_name"],
                release_date=r["release_date"], product_type=r["product_type"],
                official_product_url=r["official_product_url"],
                official_news_url=r["official_news_url"],
            )
            for r in rows
        ]


class SourceRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def upsert(
        self,
        *,
        source_name: str,
        source_type: str,
        base_url: str,
        trust_score: int,
        is_active: bool = True,
    ) -> int:
        async with self._db.pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO sources (source_name, source_type, base_url, trust_score, is_active)
                   VALUES ($1, $2, $3, $4, $5)
                   ON CONFLICT (source_name) DO UPDATE SET
                       source_type = EXCLUDED.source_type,
                       base_url = EXCLUDED.base_url,
                       trust_score = EXCLUDED.trust_score,
                       is_active = EXCLUDED.is_active,
                       updated_at = CURRENT_TIMESTAMP
                   RETURNING id""",
                source_name, source_type, base_url, trust_score, is_active,
            )
        return row["id"]

    @staticmethod
    def _row_to_source(r) -> Source:
        return Source(
            id=r["id"],
            source_name=r["source_name"],
            source_type=r["source_type"],
            base_url=r["base_url"],
            trust_score=r["trust_score"],
            is_active=r["is_active"],
            last_success_at=r["last_success_at"],
            last_attempt_at=r["last_attempt_at"],
            consecutive_failures=r["consecutive_failures"],
            last_error=r["last_error"],
        )

    async def get_by_name(self, source_name: str) -> Source | None:
        async with self._db.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM sources WHERE source_name = $1", source_name
            )
        if not row:
            return None
        return self._row_to_source(row)

    async def list_active(self) -> list[Source]:
        async with self._db.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM sources WHERE is_active = TRUE ORDER BY trust_score DESC"
            )
        return [self._row_to_source(r) for r in rows]

    async def record_success(self, source_id: int, at: datetime) -> None:
        async with self._db.pool.acquire() as conn:
            await conn.execute(
                """UPDATE sources SET last_success_at = $1, last_attempt_at = $1,
                       consecutive_failures = 0, last_error = NULL,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE id = $2""",
                at, source_id,
            )

    async def record_failure(self, source_id: int, at: datetime, err: str) -> None:
        async with self._db.pool.acquire() as conn:
            await conn.execute(
                """UPDATE sources SET last_attempt_at = $1,
                       consecutive_failures = consecutive_failures + 1,
                       last_error = $2, updated_at = CURRENT_TIMESTAMP
                   WHERE id = $3""",
                at, err, source_id,
            )


class LotteryEventRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    @property
    def pool(self):
        return self._db.pool

    async def find_by_dedupe_key(self, dedupe_key: str) -> LotteryEvent | None:
        async with self._db.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM lottery_events WHERE dedupe_key = $1", dedupe_key
            )
        if not row:
            return None
        return self._row_to_event(row)

    async def find_by_content_key(
        self, content_dedupe_key: str
    ) -> LotteryEvent | None:
        """content_dedupe_key で既存 event を検索。

        retailer/store 非依存のため、同じ content_key を持つ event が複数ある可能性がある。
        その場合は `last_seen_at` が最新のものを返す (通常 1 件だが安全策)。
        """
        async with self._db.pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT * FROM lottery_events
                   WHERE content_dedupe_key = $1
                   ORDER BY last_seen_at DESC
                   LIMIT 1""",
                content_dedupe_key,
            )
        if not row:
            return None
        return self._row_to_event(row)

    async def create(self, **fields: Any) -> int:
        """Fields: product_id, retailer_name, store_name, canonical_title, sales_type,
        apply_start_at, apply_end_at, result_at, purchase_start_at, purchase_end_at,
        purchase_limit_text, conditions_text, source_primary_url, official_confirmation_status,
        confidence_score, dedupe_key, status, product_name_normalized,
        application_url, product_url, entry_method, sale_status, page_fingerprint,
        evidence_score, evidence_summary, retailer_event_id, confidence_level,
        content_dedupe_key.

        Optional: now (datetime) - first_seen_at / last_seen_at / updated_at に使う。
        渡さなければ DB の CURRENT_TIMESTAMP (サーバ TZ) にフォールバックする。
        JST naive な now を渡すことで、Python 側の datetime.now() との比較を TZ 整合させる。
        """
        now = fields.get("now")
        async with self._db.pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO lottery_events (
                    product_id, retailer_name, store_name, canonical_title, sales_type,
                    apply_start_at, apply_end_at, result_at, purchase_start_at, purchase_end_at,
                    purchase_limit_text, conditions_text, source_primary_url,
                    official_confirmation_status, confidence_score, dedupe_key, status,
                    product_name_normalized,
                    application_url, product_url, entry_method, sale_status,
                    page_fingerprint, evidence_score, evidence_summary,
                    retailer_event_id, confidence_level, content_dedupe_key,
                    first_seen_at, last_seen_at, updated_at
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,
                          $19,$20,$21,$22,$23,$24,$25,$26,$27,$28,
                          COALESCE($29, CURRENT_TIMESTAMP),
                          COALESCE($29, CURRENT_TIMESTAMP),
                          COALESCE($29, CURRENT_TIMESTAMP))
                RETURNING id""",
                fields.get("product_id"), fields["retailer_name"], fields.get("store_name"),
                fields["canonical_title"], fields["sales_type"],
                fields.get("apply_start_at"), fields.get("apply_end_at"), fields.get("result_at"),
                fields.get("purchase_start_at"), fields.get("purchase_end_at"),
                fields.get("purchase_limit_text"), fields.get("conditions_text"),
                fields.get("source_primary_url"),
                fields.get("official_confirmation_status", "unconfirmed"),
                fields.get("confidence_score", 0),
                fields["dedupe_key"],
                fields.get("status", "active"),
                fields.get("product_name_normalized"),
                fields.get("application_url"),
                fields.get("product_url"),
                fields.get("entry_method", "unknown"),
                fields.get("sale_status", "unknown"),
                fields.get("page_fingerprint"),
                fields.get("evidence_score"),
                fields.get("evidence_summary"),
                fields.get("retailer_event_id"),
                fields.get("confidence_level"),
                fields.get("content_dedupe_key"),
                now,
            )
        return row["id"]

    async def update(
        self, event_id: int, *, now: datetime | None = None, **fields: Any
    ) -> None:
        """Update selected fields and bump updated_at + last_seen_at.

        now を渡すと last_seen_at / updated_at に JST naive 値を使う (TZ 整合)。
        """
        if not fields:
            return
        cols = list(fields.keys())
        placeholders = ", ".join(f"{c} = ${i+2}" for i, c in enumerate(cols))
        ts_expr = f"${len(cols) + 2}" if now is not None else "CURRENT_TIMESTAMP"
        query = (
            f"UPDATE lottery_events SET {placeholders}, "
            f"last_seen_at = {ts_expr}, updated_at = {ts_expr} "
            f"WHERE id = $1"
        )
        values: list[Any] = [fields[c] for c in cols]
        if now is not None:
            values.append(now)
        async with self._db.pool.acquire() as conn:
            await conn.execute(query, event_id, *values)

    async def touch_last_seen(self, event_id: int, at: datetime) -> None:
        async with self._db.pool.acquire() as conn:
            await conn.execute(
                "UPDATE lottery_events SET last_seen_at = $1 WHERE id = $2",
                at, event_id,
            )

    async def list_active(self, limit: int = 100) -> list[LotteryEvent]:
        async with self._db.pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT * FROM lottery_events WHERE status = 'active'
                   ORDER BY last_seen_at DESC LIMIT $1""",
                limit,
            )
        return [self._row_to_event(r) for r in rows]

    async def list_active_since(
        self, since: datetime, *, limit: int = 200
    ) -> list[LotteryEvent]:
        """first_seen_at >= since の active event を新しい順に返す。

        古い告知 (store_voice feed の過去履歴) を通知対象から除外するためのフィルタ。
        """
        async with self._db.pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT * FROM lottery_events
                   WHERE status = 'active' AND first_seen_at >= $1
                   ORDER BY first_seen_at DESC LIMIT $2""",
                since, limit,
            )
        return [self._row_to_event(r) for r in rows]

    async def list_ending_soon(
        self,
        *,
        now: datetime,
        within: timedelta,
        limit: int = 100,
    ) -> list[LotteryEvent]:
        """apply_end_at が now から within 以内 (かつ 未過ぎ) の active event。

        締切前 alert の対象。例: within=3h で 3時間以内に締切を迎える抽選。
        """
        async with self._db.pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT * FROM lottery_events
                   WHERE status = 'active'
                     AND apply_end_at IS NOT NULL
                     AND apply_end_at > $1
                     AND apply_end_at <= $2
                   ORDER BY apply_end_at ASC LIMIT $3""",
                now, now + within, limit,
            )
        return [self._row_to_event(r) for r in rows]

    async def list_recently_updated_since(
        self, since: datetime, *, limit: int = 100
    ) -> list[LotteryEvent]:
        """updated_at >= since かつ active の event。update 通知候補。"""
        async with self._db.pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT * FROM lottery_events
                   WHERE status = 'active' AND updated_at >= $1
                   ORDER BY updated_at DESC LIMIT $2""",
                since, limit,
            )
        return [self._row_to_event(r) for r in rows]

    async def add_source_link(
        self,
        lottery_event_id: int,
        source_id: int,
        *,
        source_url: str,
        source_title: str | None,
        source_published_at: datetime | None,
        raw_snapshot_hash: str,
        extracted_payload: dict | None,
        evidence_type: str = "unknown",
        evidence_strength: int | None = None,
        selector_version: str = "",
        canonical_fields: dict | None = None,
        raw_text_excerpt: str = "",
        retailer_name: str | None = None,
        store_name: str | None = None,
    ) -> None:
        async with self._db.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO lottery_event_sources (
                    lottery_event_id, source_id, source_url, source_title,
                    source_published_at, raw_snapshot_hash, extracted_payload_json,
                    evidence_type, evidence_strength, selector_version,
                    canonical_fields_json, raw_text_excerpt,
                    retailer_name, store_name
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
                ON CONFLICT (lottery_event_id, source_id, raw_snapshot_hash) DO NOTHING""",
                lottery_event_id, source_id, source_url, source_title,
                source_published_at, raw_snapshot_hash,
                json.dumps(extracted_payload, ensure_ascii=False, default=str) if extracted_payload else None,
                evidence_type,
                evidence_strength,
                selector_version,
                json.dumps(canonical_fields, ensure_ascii=False, default=str) if canonical_fields else None,
                raw_text_excerpt,
                retailer_name,
                store_name,
            )

    @staticmethod
    def _row_to_event(r) -> LotteryEvent:
        # asyncpg Record は keys() を持つので、存在しないカラムは KeyError を吐く。
        # 新カラムは nullable なので .get 相当として getattr + try で安全に取り出す。
        def _g(key: str, default=None):
            try:
                return r[key]
            except (KeyError, IndexError):
                return default

        return LotteryEvent(
            id=r["id"], product_id=r["product_id"],
            retailer_name=r["retailer_name"], store_name=r["store_name"],
            canonical_title=r["canonical_title"], sales_type=r["sales_type"],
            apply_start_at=r["apply_start_at"], apply_end_at=r["apply_end_at"],
            result_at=r["result_at"], purchase_start_at=r["purchase_start_at"],
            purchase_end_at=r["purchase_end_at"],
            purchase_limit_text=r["purchase_limit_text"],
            conditions_text=r["conditions_text"],
            source_primary_url=r["source_primary_url"],
            official_confirmation_status=r["official_confirmation_status"],
            confidence_score=r["confidence_score"], dedupe_key=r["dedupe_key"],
            status=r["status"], first_seen_at=r["first_seen_at"],
            last_seen_at=r["last_seen_at"],
            product_name_normalized=r["product_name_normalized"],
            application_url=_g("application_url"),
            product_url=_g("product_url"),
            entry_method=_g("entry_method", "unknown") or "unknown",
            sale_status=_g("sale_status", "unknown") or "unknown",
            page_fingerprint=_g("page_fingerprint"),
            evidence_score=_g("evidence_score"),
            evidence_summary=_g("evidence_summary"),
            retailer_event_id=_g("retailer_event_id"),
            confidence_level=_g("confidence_level"),
            content_dedupe_key=_g("content_dedupe_key"),
        )

    async def list_other_stores_for_product(
        self,
        *,
        product_name_normalized: str,
        exclude_event_id: int,
        limit: int = 10,
    ) -> list[tuple[str, str]]:
        """同じ product の他の active event + event_sources 経由の retailer/store を返す。

        new 通知時に「他N店舗でも取扱」を追記するための情報取得に使う。
        dedupe 刷新後は同一 event に複数 retailer が紐付くので、lottery_event_sources
        から retailer/store を拾う必要がある。event 本体の primary retailer/store と
        sources の retailer/store を union で返し、重複は排除する。

        store_name が NULL の event も拾えるよう COALESCE で空文字に置換する。
        """
        if not product_name_normalized:
            return []
        async with self._db.pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT DISTINCT retailer_name, store_name FROM (
                       SELECT le.retailer_name AS retailer_name,
                              COALESCE(le.store_name, '') AS store_name
                         FROM lottery_events le
                        WHERE le.product_name_normalized = $1
                          AND le.status = 'active'
                          AND le.id != $2
                       UNION ALL
                       SELECT les.retailer_name AS retailer_name,
                              COALESCE(les.store_name, '') AS store_name
                         FROM lottery_event_sources les
                         JOIN lottery_events le2 ON le2.id = les.lottery_event_id
                        WHERE le2.product_name_normalized = $1
                          AND le2.status = 'active'
                          AND les.retailer_name IS NOT NULL
                          AND (
                                le2.id != $2
                                OR les.retailer_name != le2.retailer_name
                                OR COALESCE(les.store_name, '')
                                   != COALESCE(le2.store_name, '')
                              )
                   ) t
                   WHERE retailer_name IS NOT NULL
                   ORDER BY retailer_name, store_name
                   LIMIT $3""",
                product_name_normalized, exclude_event_id, limit,
            )
        return [(r["retailer_name"], r["store_name"] or "") for r in rows]

    async def count_distinct_sources_for_product(
        self,
        product_name_normalized: str | None,
        *,
        exclude_event_id: int | None = None,
    ) -> int:
        """指定 product が何種類の source から検出されているかを返す。

        クロスソース corroboration: 同一商品が 2+ ソースで検出されたら
        confidence にボーナスを付ける判定に使う。
        """
        if not product_name_normalized:
            return 0
        sql = (
            "SELECT COUNT(DISTINCT les.source_id) "
            "FROM lottery_event_sources les "
            "JOIN lottery_events le ON le.id = les.lottery_event_id "
            "WHERE le.product_name_normalized = $1"
        )
        args: list = [product_name_normalized]
        if exclude_event_id is not None:
            sql += " AND le.id != $2"
            args.append(exclude_event_id)
        async with self._db.pool.acquire() as conn:
            val = await conn.fetchval(sql, *args)
        return val or 0


class NotificationRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def try_claim(
        self,
        *,
        lottery_event_id: int,
        notification_type: str,
        channel: str,
        dedupe_key: str,
        payload_summary: str,
    ) -> int | None:
        """Atomically insert a notification row. Return id if claimed (must send), None if already exists."""
        async with self._db.pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO notifications (lottery_event_id, notification_type, channel,
                       dedupe_key, payload_summary)
                   VALUES ($1, $2, $3, $4, $5)
                   ON CONFLICT (dedupe_key) DO NOTHING
                   RETURNING id""",
                lottery_event_id, notification_type, channel, dedupe_key, payload_summary,
            )
        return row["id"] if row else None

    async def mark_sent(self, notification_id: int, at: datetime) -> None:
        async with self._db.pool.acquire() as conn:
            await conn.execute(
                "UPDATE notifications SET sent_at = $1 WHERE id = $2",
                at, notification_id,
            )

    async def has_notification_sent(
        self, *, lottery_event_id: int, notification_type: str
    ) -> bool:
        """指定 event × type の通知が sent 済みかどうか。"""
        async with self._db.pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT 1 FROM notifications
                   WHERE lottery_event_id = $1 AND notification_type = $2
                     AND sent_at IS NOT NULL LIMIT 1""",
                lottery_event_id, notification_type,
            )
        return row is not None

    async def get_last_sent_at(
        self, *, lottery_event_id: int, notification_type: str
    ) -> datetime | None:
        """指定 event × type の最新 sent_at を返す (ない場合 None)。"""
        async with self._db.pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT MAX(sent_at) AS last_sent FROM notifications
                   WHERE lottery_event_id = $1 AND notification_type = $2
                     AND sent_at IS NOT NULL""",
                lottery_event_id, notification_type,
            )
        return row["last_sent"] if row and row["last_sent"] else None

    async def is_dedupe_claimed(self, dedupe_key: str) -> bool:
        """指定 dedupe_key の notification 行が既に存在するか (sent 済みか否かを問わない)。

        dry-run で、本番なら try_claim が None を返す条件を事前に判定するための READ-ONLY 版。
        try_claim の ON CONFLICT (dedupe_key) と同じ観点で衝突判定する。
        """
        async with self._db.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT 1 FROM notifications WHERE dedupe_key = $1 LIMIT 1",
                dedupe_key,
            )
        return row is not None

    async def has_sent_with_summary(
        self, *, lottery_event_id: int, summary: str
    ) -> bool:
        """指定 event に対して、同一 payload_summary で sent 済みの通知が存在するか。

        告知内容 (メッセージ文面) が変わっていない update を抑止するために使う。
        new / update / deadline を横断して判定する (LINE に届く通知種別を全て対象)。
        """
        async with self._db.pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT 1 FROM notifications
                   WHERE lottery_event_id = $1
                     AND payload_summary = $2
                     AND sent_at IS NOT NULL
                     AND notification_type IN ('new', 'update', 'deadline', 'result')
                   LIMIT 1""",
                lottery_event_id, summary,
            )
        return row is not None

    async def get_last_sent_for_product(
        self,
        *,
        product_name_normalized: str,
        notification_types: tuple[str, ...] = ("new",),
    ) -> datetime | None:
        """指定 product_name_normalized に紐づく lottery_events を対象に、
        指定 type の最新 sent_at を返す。product 単位の重複通知抑止に使用。
        """
        if not product_name_normalized:
            return None
        async with self._db.pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT MAX(n.sent_at) AS last_sent
                   FROM notifications n
                   JOIN lottery_events le ON le.id = n.lottery_event_id
                   WHERE le.product_name_normalized = $1
                     AND n.notification_type = ANY($2::text[])
                     AND n.sent_at IS NOT NULL""",
                product_name_normalized, list(notification_types),
            )
        return row["last_sent"] if row and row["last_sent"] else None
