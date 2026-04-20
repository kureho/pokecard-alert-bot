from datetime import datetime, timedelta

import pytest
from pokebot.models import Event, EventKind, Priority
from pokebot.retention import prune_old_events
from pokebot.storage.repo import EventRepo


def _ev(key: str, url: str) -> Event:
    return Event(
        source="yodobashi", kind=EventKind.LOTTERY_OPEN,
        product_name="x", product_raw="x",
        normalized_key=key, url=url,
        detected_at=datetime(2026, 4, 20, 12), priority=Priority.CRITICAL,
    )


async def _count(repo: EventRepo) -> int:
    async with repo.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT COUNT(*) AS c FROM events")
    return row["c"]


@pytest.mark.asyncio
async def test_prune_deletes_old_notified_events(db):
    repo = EventRepo(db)
    now = datetime(2026, 10, 20, 12)
    old_notified = _ev("k1", "https://x/1")
    await repo.insert_if_new(old_notified)
    await repo.mark_notified(old_notified.id, now - timedelta(days=181))
    recent_notified = _ev("k2", "https://x/2")
    await repo.insert_if_new(recent_notified)
    await repo.mark_notified(recent_notified.id, now - timedelta(days=10))
    deleted = await prune_old_events(repo, now=now)
    assert deleted == 1
    assert await _count(repo) == 1


@pytest.mark.asyncio
async def test_prune_keeps_unnotified_even_if_old(db):
    repo = EventRepo(db)
    now = datetime(2026, 10, 20, 12)
    old_unnotified = _ev("k1", "https://x/1")
    await repo.insert_if_new(old_unnotified)
    async with repo.pool.acquire() as conn:
        await conn.execute(
            "UPDATE events SET detected_at = $1 WHERE id = $2",
            now - timedelta(days=200), old_unnotified.id,
        )
    deleted = await prune_old_events(repo, now=now)
    assert deleted == 0
    assert await _count(repo) == 1


@pytest.mark.asyncio
async def test_prune_respects_custom_retention(db):
    repo = EventRepo(db)
    now = datetime(2026, 10, 20, 12)
    ev = _ev("k1", "https://x/1")
    await repo.insert_if_new(ev)
    await repo.mark_notified(ev.id, now - timedelta(days=30))
    deleted = await prune_old_events(repo, now=now, retain=timedelta(days=20))
    assert deleted == 1
