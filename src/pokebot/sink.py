from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Iterable
from datetime import datetime

from .monitors.types import RawItem
from .pipeline import to_event
from .storage.repo import EventRepo, SourceHealthRepo

log = logging.getLogger(__name__)
NowFn = Callable[[], datetime]


def make_sink(
    event_repo: EventRepo,
    health_repo: SourceHealthRepo,
    *,
    now_fn: NowFn = datetime.now,
) -> Callable[..., Awaitable[None]]:
    async def sink(
        monitor_id: str,
        items: Iterable[RawItem],
        ok: bool,
        err: Exception | None = None,
    ) -> None:
        now = now_fn()
        if not ok:
            await health_repo.record_failure(monitor_id, now, str(err) if err else "unknown")
            return
        # 初回スクレイプ判定: 当該ソースで成功記録がまだない = 過去ニュース全件の洪水を防ぐため notified 扱いで seed
        existing = await health_repo.get(monitor_id)
        is_first_run = existing is None or existing.last_success_at is None
        seed_notified_at = now if is_first_run else None
        inserted = 0
        for item in items:
            ev = to_event(item, now=now)
            if ev is None:
                continue
            if await event_repo.insert_if_new(ev, notified_at=seed_notified_at):
                inserted += 1
        await health_repo.record_success(monitor_id, now, nonzero=inserted > 0)
        if is_first_run and inserted:
            log.info("first-run seed for %s: %d events marked notified (no push)", monitor_id, inserted)

    return sink
