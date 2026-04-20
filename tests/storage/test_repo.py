from datetime import datetime

import pytest

from pokebot.models import Event, EventKind, Priority
from pokebot.storage.repo import EventRepo, SourceHealthRepo


def make_event(**kw) -> Event:
    base = dict(
        source="yodobashi",
        kind=EventKind.LOTTERY_OPEN,
        product_name="テラスタルフェスex BOX",
        product_raw="【抽選】テラスタルフェスex BOX",
        normalized_key="拡張パック|テラスタルフェスex|2026-03-14|BOX",
        url="https://www.yodobashi.com/x",
        detected_at=datetime(2026, 4, 20, 12, 0, 0),
        priority=Priority.CRITICAL,
    )
    base.update(kw)
    return Event(**base)


@pytest.mark.asyncio
async def test_insert_returns_true_for_new(db):
    repo = EventRepo(db)
    assert await repo.insert_if_new(make_event()) is True


@pytest.mark.asyncio
async def test_insert_returns_false_for_duplicate(db):
    repo = EventRepo(db)
    ev = make_event()
    await repo.insert_if_new(ev)
    assert await repo.insert_if_new(ev) is False


@pytest.mark.asyncio
async def test_pending_notifications_returns_unnotified(db):
    repo = EventRepo(db)
    ev = make_event()
    await repo.insert_if_new(ev)
    pending = await repo.pending_notifications()
    assert len(pending) == 1
    assert pending[0].id == ev.id


@pytest.mark.asyncio
async def test_mark_notified(db):
    repo = EventRepo(db)
    ev = make_event()
    await repo.insert_if_new(ev)
    await repo.mark_notified(ev.id, datetime(2026, 4, 20, 12, 1))
    assert await repo.pending_notifications() == []


@pytest.mark.asyncio
async def test_source_health_upsert(db):
    repo = SourceHealthRepo(db)
    await repo.record_success("yodobashi", datetime(2026, 4, 20), nonzero=True)
    rec = await repo.get("yodobashi")
    assert rec.consecutive_failures == 0
    assert rec.last_nonzero_detection_at is not None


@pytest.mark.asyncio
async def test_source_health_failure_increments(db):
    repo = SourceHealthRepo(db)
    await repo.record_failure("yodobashi", datetime(2026, 4, 20), "boom")
    await repo.record_failure("yodobashi", datetime(2026, 4, 20, 0, 1), "boom")
    rec = await repo.get("yodobashi")
    assert rec.consecutive_failures == 2
