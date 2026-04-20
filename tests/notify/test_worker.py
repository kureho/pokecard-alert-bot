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
async def test_silently_acks_non_notify_kinds(db):
    """ANNOUNCEMENT / NEW_PRODUCT は LINE 送信せず DB 通知済みマークのみ。"""
    repo = EventRepo(db)
    notifier = FakeNotifier()
    for kind in (EventKind.ANNOUNCEMENT, EventKind.NEW_PRODUCT):
        await repo.insert_if_new(
            _ev(kind=kind, normalized_key=f"k-{kind.value}", url=f"https://ex/{kind.value}")
        )
    worker = NotifyWorker(repo, notifier)
    await worker.tick(now=datetime(2026, 4, 20, 12, 1))
    assert notifier.sent == []
    assert await repo.pending_notifications() == []


@pytest.mark.asyncio
async def test_max_per_run_caps_sends(db):
    """max_per_run を超えたら残りは pending のまま残す。"""
    repo = EventRepo(db)
    notifier = FakeNotifier()
    for i in range(5):
        await repo.insert_if_new(
            _ev(normalized_key=f"k{i}", url=f"https://ex.com/{i}")
        )
    worker = NotifyWorker(repo, notifier, max_per_run=2)
    await worker.tick(now=datetime(2026, 4, 20, 12, 1))
    assert len(notifier.sent) == 2
    assert len(await repo.pending_notifications()) == 3


@pytest.mark.asyncio
async def test_max_per_day_caps_sends(db):
    """24h以内の通知実績＋今回送信合計が max_per_day を超えたら抑止。"""
    from datetime import timedelta as _td
    repo = EventRepo(db)
    notifier = FakeNotifier()
    # 24h以内に3件送信済みを仕込む
    for i in range(3):
        ev = _ev(normalized_key=f"past{i}", url=f"https://past/{i}")
        await repo.insert_if_new(ev)
        await repo.mark_notified(ev.id, datetime(2026, 4, 20, 10) - _td(hours=i))
    # 新規 pending を5件
    for i in range(5):
        await repo.insert_if_new(
            _ev(normalized_key=f"new{i}", url=f"https://new/{i}")
        )
    worker = NotifyWorker(repo, notifier, max_per_day=5)
    await worker.tick(now=datetime(2026, 4, 20, 12))
    # 既に3件24h以内にある → 残り2件のみ送信可能
    assert len(notifier.sent) == 2


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
        row = await conn.fetchrow("SELECT extra_json, notified_at FROM events WHERE id = $1", ev.id)
    assert row is not None
    extra = json.loads(row["extra_json"]) if row["extra_json"] else {}
    assert extra.get("notify_giveup") is True
