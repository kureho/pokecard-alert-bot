from datetime import datetime, timedelta

import pytest
from pokebot.monitors.types import RawItem
from pokebot.sink import make_sink
from pokebot.storage.repo import EventRepo, SourceHealthRepo


async def _seed_prior_success(health_repo: SourceHealthRepo, source: str, at: datetime) -> None:
    """このソースで過去に成功履歴があることを示す。以降の sink 呼び出しは通常の pending 扱い。"""
    await health_repo.record_success(source, at, nonzero=False)


@pytest.mark.asyncio
async def test_sink_inserts_events_and_records_success(db):
    event_repo = EventRepo(db)
    health_repo = SourceHealthRepo(db)
    now = datetime(2026, 4, 20, 12)
    await _seed_prior_success(health_repo, "yodobashi_lottery", now - timedelta(minutes=5))
    sink = make_sink(event_repo, health_repo, now_fn=lambda: now)
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
async def test_sink_first_run_seeds_as_notified(db):
    """初回スクレイプで過去ニュース全件を LINE に送りつけないことを検証。"""
    event_repo = EventRepo(db)
    health_repo = SourceHealthRepo(db)
    sink = make_sink(event_repo, health_repo, now_fn=lambda: datetime(2026, 4, 20, 12))
    items = [
        RawItem(
            source="pokemon_card_news",
            raw_title=f"記事{i} 発売情報",
            url=f"https://ex.com/{i}",
            kind_hint="new_product",
        )
        for i in range(5)
    ]
    await sink("pokemon_card_news", items, True)
    # 初回は全て notified 済みで挿入される → pending は空
    assert await event_repo.pending_notifications() == []
    # DB には残っており次回以降の重複排除に使える
    async with event_repo.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT COUNT(*) AS c FROM events")
    assert row["c"] == 5


@pytest.mark.asyncio
async def test_sink_second_run_notifies_new_items(db):
    """2回目以降のスクレイプでは新規検知は pending 化される。"""
    event_repo = EventRepo(db)
    health_repo = SourceHealthRepo(db)
    sink = make_sink(event_repo, health_repo, now_fn=lambda: datetime(2026, 4, 20, 12))
    first = [
        RawItem(
            source="pokemon_card_news",
            raw_title="記事1 発売",
            url="https://ex.com/1",
            kind_hint="new_product",
        )
    ]
    await sink("pokemon_card_news", first, True)
    second = [
        RawItem(
            source="pokemon_card_news",
            raw_title="記事2 新弾",
            url="https://ex.com/2",
            kind_hint="new_product",
        )
    ]
    await sink("pokemon_card_news", second, True)
    pending = await event_repo.pending_notifications()
    assert len(pending) == 1
    assert "記事2" in pending[0].product_raw


@pytest.mark.asyncio
async def test_sink_deduplicates_identical_item_on_second_call(db):
    event_repo = EventRepo(db)
    health_repo = SourceHealthRepo(db)
    now = datetime(2026, 4, 20, 12)
    await _seed_prior_success(health_repo, "yodobashi_lottery", now - timedelta(minutes=5))
    sink = make_sink(event_repo, health_repo, now_fn=lambda: now)
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
