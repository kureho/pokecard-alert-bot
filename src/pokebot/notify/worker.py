from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

from tenacity import AsyncRetrying, RetryError, stop_after_attempt, wait_exponential

from ..models import EventKind
from ..storage.repo import EventRepo
from .aggregation import AggregationBuffer
from .formatter import format_aggregation, format_event
from .line import Notifier

log = logging.getLogger(__name__)

GIVEUP_AFTER = timedelta(hours=24)

# LINE に push 対象とする kind のホワイトリスト。
# ANNOUNCEMENT / NEW_PRODUCT は DB には記録するが通知しない（ノイズ防止）。
NOTIFY_KINDS: frozenset[EventKind] = frozenset(
    {
        EventKind.LOTTERY_OPEN,
        EventKind.LOTTERY_CLOSE,
        EventKind.RESTOCK,
        EventKind.LOTTERY_RESULT,
    }
)


class NotifyWorker:
    def __init__(
        self,
        repo: EventRepo,
        notifier: Notifier,
        aggregator: AggregationBuffer | None = None,
    ) -> None:
        self._repo = repo
        self._notifier = notifier
        self._agg = aggregator

    async def tick(self, *, now: datetime) -> None:
        # 1. 各 pending を処理
        for ev in await self._repo.pending_notifications():
            if ev.kind not in NOTIFY_KINDS:
                # kind allowlist 外は silent ack（DB に記録のみ）
                await self._repo.mark_notified(ev.id, now)
                continue
            if now - ev.detected_at > GIVEUP_AFTER:
                await self._mark_giveup(ev.id)
                log.warning("notify giveup: %s", ev.id)
                continue
            if self._agg and (await self._agg.classify(ev, now=now)) == "buffer":
                await self._agg.enqueue(ev, now=now)
                continue
            try:
                async for attempt in AsyncRetrying(
                    stop=stop_after_attempt(3),
                    wait=wait_exponential(multiplier=1, min=1, max=30),
                    reraise=True,
                ):
                    with attempt:
                        await self._notifier.send(format_event(ev))
                await self._repo.mark_notified(ev.id, now)
            except RetryError:
                log.warning("notify retry exhausted: %s", ev.id)
            except Exception as e:  # noqa: BLE001
                log.warning("notify error: %s %s", ev.id, e)

        # 2. 集約ウィンドウ到達分
        if self._agg:
            groups = await self._agg.drain_due(now)
            for _key, events in groups.items():
                head = events[0]
                msg = format_aggregation(head, events)
                try:
                    await self._notifier.send(msg)
                    for e in events:
                        await self._repo.mark_notified(e.id, now)
                except Exception as e:  # noqa: BLE001
                    log.warning("aggregation notify error: %s", e)

    async def _mark_giveup(self, event_id: str) -> None:
        async with self._repo.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT extra_json FROM events WHERE id = $1", event_id)
            extra = json.loads(row["extra_json"]) if row and row["extra_json"] else {}
            extra["notify_giveup"] = True
            await conn.execute(
                "UPDATE events SET extra_json = $1 WHERE id = $2",
                json.dumps(extra, ensure_ascii=False),
                event_id,
            )
