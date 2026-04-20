from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from ..models import Event
from ..storage.repo import EventRepo

AGGREGATION_WINDOW = timedelta(minutes=10)


class AggregationBuffer:
    def __init__(self, repo: EventRepo) -> None:
        self._repo = repo

    async def classify(self, ev: Event, *, now: datetime) -> Literal["send_now", "buffer"]:
        async with self._repo.pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT 1 FROM events
                   WHERE normalized_key = $1 AND notified_at IS NOT NULL
                     AND id != $2 LIMIT 1""",
                ev.normalized_key,
                ev.id,
            )
        return "buffer" if row else "send_now"

    async def enqueue(self, ev: Event, *, now: datetime) -> None:
        async with self._repo.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO pending_aggregations
                       (normalized_key, event_id, scheduled_at) VALUES ($1, $2, $3)
                   ON CONFLICT (normalized_key, event_id) DO UPDATE SET
                       scheduled_at = EXCLUDED.scheduled_at""",
                ev.normalized_key,
                ev.id,
                now + AGGREGATION_WINDOW,
            )

    async def drain_due(self, now: datetime) -> dict[str, list[Event]]:
        async with self._repo.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT normalized_key, event_id FROM pending_aggregations "
                "WHERE scheduled_at <= $1",
                now,
            )
            if not rows:
                return {}
            keys = {r["normalized_key"] for r in rows}
            event_ids = [r["event_id"] for r in rows]
            ev_rows = await conn.fetch("SELECT * FROM events WHERE id = ANY($1::text[])", event_ids)
            await conn.execute(
                "DELETE FROM pending_aggregations WHERE event_id = ANY($1::text[])",
                event_ids,
            )

        from ..storage.repo import EventRepo as _R

        groups: dict[str, list[Event]] = {k: [] for k in keys}
        for r in ev_rows:
            ev = _R._row_to_event(r)
            groups[ev.normalized_key].append(ev)
        return groups
