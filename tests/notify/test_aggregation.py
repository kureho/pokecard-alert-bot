from datetime import datetime

import pytest

from pokebot.models import Event, EventKind, Priority
from pokebot.notify.aggregation import AggregationBuffer
from pokebot.storage.repo import EventRepo


def _ev(source="yodobashi", key="k1", url="https://x", kind=EventKind.LOTTERY_OPEN, **kw):
    base = dict(
        source=source,
        kind=kind,
        product_name="X BOX",
        product_raw="raw",
        normalized_key=key,
        url=url,
        detected_at=datetime(2026, 4, 20, 12),
        priority=Priority.CRITICAL,
    )
    base.update(kw)
    return Event(**base)


@pytest.mark.asyncio
async def test_first_detection_is_send_now(db):
    repo = EventRepo(db)
    buf = AggregationBuffer(repo)
    decision = await buf.classify(_ev(), now=datetime(2026, 4, 20, 12))
    assert decision == "send_now"


@pytest.mark.asyncio
async def test_second_source_same_key_is_buffered(db):
    repo = EventRepo(db)
    buf = AggregationBuffer(repo)
    first = _ev(source="yodobashi")
    await repo.insert_if_new(first)
    await repo.mark_notified(first.id, datetime(2026, 4, 20, 12))
    second = _ev(source="bic", url="https://bic")
    decision = await buf.classify(second, now=datetime(2026, 4, 20, 12, 1))
    assert decision == "buffer"


@pytest.mark.asyncio
async def test_drain_returns_events_past_scheduled_at(db):
    repo = EventRepo(db)
    buf = AggregationBuffer(repo)
    first = _ev(source="yodobashi")
    await repo.insert_if_new(first)
    await repo.mark_notified(first.id, datetime(2026, 4, 20, 12))
    second = _ev(source="bic", url="https://bic")
    await repo.insert_if_new(second)
    await buf.enqueue(second, now=datetime(2026, 4, 20, 12, 1))
    assert await buf.drain_due(datetime(2026, 4, 20, 12, 6)) == {}
    groups = await buf.drain_due(datetime(2026, 4, 20, 12, 12))
    assert "k1" in groups
    assert len(groups["k1"]) == 1
