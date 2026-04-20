import json
from datetime import datetime

import pytest

from pokebot.models import Event, EventKind, Priority
from pokebot.notify.worker import NotifyWorker
from pokebot.storage.repo import EventRepo


class FakeNotifier:
    def __init__(self, fail_n: int = 0):
        self.sent: list[str] = []
        self.fail_n = fail_n

    async def send(self, text: str) -> None:
        if len(self.sent) < self.fail_n:
            self.sent.append(text)
            raise RuntimeError("boom")
        self.sent.append(text)


def _ev(**kw) -> Event:
    base = dict(
        source="yodobashi",
        kind=EventKind.LOTTERY_OPEN,
        product_name="x",
        product_raw="raw",
        normalized_key="k",
        url="https://ex.com",
        detected_at=datetime(2026, 4, 20, 12),
        priority=Priority.CRITICAL,
    )
    base.update(kw)
    return Event(**base)


@pytest.mark.asyncio
async def test_sends_and_marks_notified(db):
    repo = EventRepo(db)
    notifier = FakeNotifier()
    await repo.insert_if_new(_ev())
    worker = NotifyWorker(repo, notifier)
    await worker.tick(now=datetime(2026, 4, 20, 12, 2))
    assert len(notifier.sent) == 1
    assert await repo.pending_notifications() == []


@pytest.mark.asyncio
async def test_retries_on_failure(db):
    repo = EventRepo(db)
    notifier = FakeNotifier(fail_n=2)
    await repo.insert_if_new(_ev())
    worker = NotifyWorker(repo, notifier)
    await worker.tick(now=datetime(2026, 4, 20, 12, 2))
    assert len(notifier.sent) == 3


@pytest.mark.asyncio
async def test_gives_up_after_24h(db):
    repo = EventRepo(db)

    class AlwaysFail:
        async def send(self, text):
            raise RuntimeError("x")

    ev = _ev(detected_at=datetime(2026, 4, 19, 10))
    await repo.insert_if_new(ev)
    worker = NotifyWorker(repo, AlwaysFail())
    await worker.tick(now=datetime(2026, 4, 20, 12, 2))
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT extra_json, notified_at FROM events WHERE id = $1", ev.id
        )
    assert row is not None
    extra = json.loads(row["extra_json"]) if row["extra_json"] else {}
    assert extra.get("notify_giveup") is True
