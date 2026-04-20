from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from datetime import datetime

from .monitors.types import RawItem
from .pipeline import to_event
from .storage.repo import EventRepo, SourceHealthRepo

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
        inserted = 0
        for item in items:
            ev = to_event(item, now=now)
            if ev is None:
                continue
            if await event_repo.insert_if_new(ev):
                inserted += 1
        await health_repo.record_success(monitor_id, now, nonzero=inserted > 0)

    return sink
