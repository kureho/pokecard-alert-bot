from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from ..models import Event, EventKind, Priority
from .db import Database


@dataclass
class SourceHealth:
    source: str
    last_success_at: datetime | None
    last_attempt_at: datetime | None
    last_nonzero_detection_at: datetime | None
    consecutive_failures: int
    last_error: str | None
    last_warned_at: datetime | None = None


class EventRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    @property
    def pool(self):
        return self._db.pool

    async def insert_if_new(self, ev: Event) -> bool:
        """新規なら True を返す。重複なら False。"""
        async with self._db.pool.acquire() as conn:
            status = await conn.execute(
                """INSERT INTO events (id, source, kind, product_name, product_raw,
                       normalized_key, url, detected_at, source_ts, price_yen,
                       lottery_deadline, priority, extra_json, notified_at)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,NULL)
                   ON CONFLICT (id) DO NOTHING""",
                ev.id,
                ev.source,
                ev.kind.value,
                ev.product_name,
                ev.product_raw,
                ev.normalized_key,
                ev.url,
                ev.detected_at,
                ev.source_ts,
                ev.price_yen,
                ev.lottery_deadline,
                int(ev.priority),
                json.dumps(ev.extra, ensure_ascii=False),
            )
            # asyncpg は "INSERT 0 1" / "INSERT 0 0" を返す
            return status.endswith(" 1")

    async def pending_notifications(self) -> list[Event]:
        async with self._db.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM events WHERE notified_at IS NULL ORDER BY detected_at"
            )
        return [self._row_to_event(r) for r in rows]

    async def mark_notified(self, event_id: str, at: datetime) -> None:
        async with self._db.pool.acquire() as conn:
            await conn.execute(
                "UPDATE events SET notified_at = $1 WHERE id = $2", at, event_id
            )

    @staticmethod
    def _row_to_event(r) -> Event:
        return Event(
            source=r["source"],
            kind=EventKind(r["kind"]),
            product_name=r["product_name"],
            product_raw=r["product_raw"],
            normalized_key=r["normalized_key"],
            url=r["url"],
            detected_at=r["detected_at"],
            source_ts=r["source_ts"],
            price_yen=r["price_yen"],
            lottery_deadline=r["lottery_deadline"],
            priority=Priority(r["priority"]),
            extra=json.loads(r["extra_json"]) if r["extra_json"] else {},
        )


class SourceHealthRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    @property
    def pool(self):
        return self._db.pool

    async def record_success(self, source: str, at: datetime, *, nonzero: bool) -> None:
        nonzero_at = at if nonzero else None
        async with self._db.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO source_health (source, last_success_at, last_attempt_at,
                       last_nonzero_detection_at, consecutive_failures, last_error)
                   VALUES ($1, $2, $3, $4, 0, NULL)
                   ON CONFLICT (source) DO UPDATE SET
                       last_success_at = EXCLUDED.last_success_at,
                       last_attempt_at = EXCLUDED.last_attempt_at,
                       last_nonzero_detection_at =
                           COALESCE(EXCLUDED.last_nonzero_detection_at,
                                    source_health.last_nonzero_detection_at),
                       consecutive_failures = 0,
                       last_error = NULL""",
                source,
                at,
                at,
                nonzero_at,
            )

    async def record_failure(self, source: str, at: datetime, err: str) -> None:
        async with self._db.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO source_health (source, last_attempt_at,
                       consecutive_failures, last_error)
                   VALUES ($1, $2, 1, $3)
                   ON CONFLICT (source) DO UPDATE SET
                       last_attempt_at = EXCLUDED.last_attempt_at,
                       consecutive_failures = source_health.consecutive_failures + 1,
                       last_error = EXCLUDED.last_error""",
                source,
                at,
                err,
            )

    async def get(self, source: str) -> SourceHealth | None:
        async with self._db.pool.acquire() as conn:
            r = await conn.fetchrow(
                "SELECT * FROM source_health WHERE source = $1", source
            )
        if not r:
            return None
        return SourceHealth(
            source=r["source"],
            last_success_at=r["last_success_at"],
            last_attempt_at=r["last_attempt_at"],
            last_nonzero_detection_at=r["last_nonzero_detection_at"],
            consecutive_failures=r["consecutive_failures"],
            last_error=r["last_error"],
            last_warned_at=r["last_warned_at"],
        )

    async def record_warning(self, source: str, at: datetime) -> None:
        async with self._db.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO source_health (source, last_warned_at, consecutive_failures)
                   VALUES ($1, $2, 0)
                   ON CONFLICT (source) DO UPDATE SET
                       last_warned_at = EXCLUDED.last_warned_at""",
                source, at,
            )
