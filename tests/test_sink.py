from datetime import datetime

import pytest
from pokebot.monitors.types import RawItem
from pokebot.sink import make_sink
from pokebot.storage.repo import EventRepo, SourceHealthRepo


@pytest.mark.asyncio
async def test_sink_inserts_events_and_records_success(db):
    event_repo = EventRepo(db)
    health_repo = SourceHealthRepo(db)
    sink = make_sink(event_repo, health_repo, now_fn=lambda: datetime(2026, 4, 20, 12))
    items = [
        RawItem(
            source="yodobashi",
            raw_title="【抽選】拡張パック テラスタルフェスex BOX",
            url="https://ex.com/1",
            kind_hint="lottery_open",
        )
    ]
    await sink("yodobashi_lottery", items, True)
    pending = await event_repo.pending_notifications()
    assert len(pending) == 1
    health = await health_repo.get("yodobashi_lottery")
    assert health.consecutive_failures == 0
    assert health.last_nonzero_detection_at is not None


@pytest.mark.asyncio
async def test_sink_records_failure(db):
    event_repo = EventRepo(db)
    health_repo = SourceHealthRepo(db)
    sink = make_sink(event_repo, health_repo, now_fn=lambda: datetime(2026, 4, 20, 12))
    await sink("yodobashi_lottery", [], False, err=RuntimeError("boom"))
    health = await health_repo.get("yodobashi_lottery")
    assert health.consecutive_failures == 1
    assert "boom" in (health.last_error or "")


@pytest.mark.asyncio
async def test_sink_zero_items_success_doesnt_bump_nonzero(db):
    event_repo = EventRepo(db)
    health_repo = SourceHealthRepo(db)
    sink = make_sink(event_repo, health_repo, now_fn=lambda: datetime(2026, 4, 20, 12))
    await sink("yodobashi_lottery", [], True)
    health = await health_repo.get("yodobashi_lottery")
    assert health.consecutive_failures == 0
    assert health.last_nonzero_detection_at is None


@pytest.mark.asyncio
async def test_sink_deduplicates_identical_item_on_second_call(db):
    event_repo = EventRepo(db)
    health_repo = SourceHealthRepo(db)
    sink = make_sink(event_repo, health_repo, now_fn=lambda: datetime(2026, 4, 20, 12))
    items = [
        RawItem(
            source="yodobashi",
            raw_title="【抽選】拡張パック テラスタルフェスex BOX",
            url="https://ex.com/1",
            kind_hint="lottery_open",
        )
    ]
    await sink("yodobashi_lottery", items, True)
    await sink("yodobashi_lottery", items, True)
    assert len(await event_repo.pending_notifications()) == 1
