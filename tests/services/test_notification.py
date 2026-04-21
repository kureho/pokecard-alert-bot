from datetime import datetime, timedelta

import pytest

from pokebot.adapters.base import Candidate
from pokebot.services.lottery_upsert import LotteryEventUpsertService
from pokebot.services.notification import (
    NotificationDispatcher,
    format_event_message,
)
from pokebot.storage.repos import (
    LotteryEventRepo,
    NotificationRepo,
    ProductRepo,
    SourceRepo,
)


class FakeNotifier:
    def __init__(self):
        self.sent: list[str] = []

    async def send(self, text: str) -> None:
        self.sent.append(text)


async def _seed_source(db, name="pokemon_official_news", trust=100):
    await SourceRepo(db).upsert(
        source_name=name,
        source_type="official_news",
        base_url="https://x",
        trust_score=trust,
    )


async def _create_confirmed_event(db):
    await _seed_source(db)
    svc = LotteryEventUpsertService(
        lottery_repo=LotteryEventRepo(db),
        product_repo=ProductRepo(db),
        source_repo=SourceRepo(db),
    )
    c = Candidate(
        product_name_raw="アビスアイ",
        product_name_normalized="アビスアイ",
        retailer_name="pokemoncenter_online",
        sales_type="lottery",
        canonical_title="アビスアイ抽選",
        source_name="pokemon_official_news",
        source_url="https://www.pokemon-card.com/info/1",
        source_title="アビスアイ抽選",
        raw_snapshot="h1",
        apply_start_at=datetime(2026, 5, 10, 14),
        apply_end_at=datetime(2026, 5, 14, 23, 59),
        extracted_payload={"body_fetched": True, "title_category": "lottery_active"},
    )
    out = await svc.apply(c, now=datetime(2026, 4, 21, 12))
    return out.event_id


@pytest.mark.asyncio
async def test_dispatch_sends_line_for_confirmed_high_confidence(db):
    await _create_confirmed_event(db)
    notifier = FakeNotifier()
    disp = NotificationDispatcher(
        lottery_repo=LotteryEventRepo(db),
        product_repo=ProductRepo(db),
        notification_repo=NotificationRepo(db),
        notifier=notifier,
        max_per_run=10,
        max_per_day=150,
    )
    result = await disp.dispatch(now=datetime(2026, 4, 21, 12, 5))
    assert result.new_sent == 1
    assert len(notifier.sent) == 1
    assert "[高信頼]" in notifier.sent[0]


@pytest.mark.asyncio
async def test_dispatch_suppresses_duplicate(db):
    await _create_confirmed_event(db)
    notifier = FakeNotifier()
    disp = NotificationDispatcher(
        lottery_repo=LotteryEventRepo(db),
        product_repo=ProductRepo(db),
        notification_repo=NotificationRepo(db),
        notifier=notifier,
        max_per_run=10,
        max_per_day=150,
    )
    r1 = await disp.dispatch(now=datetime(2026, 4, 21, 12, 5))
    r2 = await disp.dispatch(now=datetime(2026, 4, 21, 12, 10))
    assert r1.new_sent == 1
    assert r2.new_sent == 0
    assert r2.suppressed == 1
    assert len(notifier.sent) == 1


@pytest.mark.asyncio
async def test_dispatch_respects_per_run_cap(db):
    # 3 events, cap=2
    await _seed_source(db)
    svc = LotteryEventUpsertService(
        lottery_repo=LotteryEventRepo(db),
        product_repo=ProductRepo(db),
        source_repo=SourceRepo(db),
    )
    now = datetime(2026, 4, 21, 12)
    for i in range(3):
        c = Candidate(
            product_name_raw=f"p{i}xx",
            product_name_normalized=f"p{i}xx",
            retailer_name="pokemoncenter_online",
            sales_type="lottery",
            canonical_title=f"t{i}",
            source_name="pokemon_official_news",
            source_url=f"https://ex.com/{i}",
            source_title=f"t{i}",
            raw_snapshot=f"h{i}",
            apply_start_at=datetime(2026, 5, 10, 14),
            apply_end_at=datetime(2026, 5, 14, 23, 59),
            extracted_payload={"body_fetched": True, "title_category": "lottery_active"},
        )
        await svc.apply(c, now=now)
    notifier = FakeNotifier()
    disp = NotificationDispatcher(
        lottery_repo=LotteryEventRepo(db),
        product_repo=ProductRepo(db),
        notification_repo=NotificationRepo(db),
        notifier=notifier,
        max_per_run=2,
        max_per_day=150,
    )
    result = await disp.dispatch(now=now)
    assert result.new_sent == 2


@pytest.mark.asyncio
async def test_dispatch_skips_unconfirmed(db):
    await SourceRepo(db).upsert(
        source_name="low_trust",
        source_type="aggregator",
        base_url="https://x",
        trust_score=60,  # not official
    )
    svc = LotteryEventUpsertService(
        lottery_repo=LotteryEventRepo(db),
        product_repo=ProductRepo(db),
        source_repo=SourceRepo(db),
    )
    c = Candidate(
        product_name_raw="pXYZ",
        product_name_normalized="pXYZ",
        retailer_name="unknown",
        sales_type="lottery",
        canonical_title="t",
        source_name="low_trust",
        source_url="https://x",
        source_title="t",
        raw_snapshot="h",
        apply_start_at=datetime(2026, 5, 10, 14),
        apply_end_at=datetime(2026, 5, 14, 23, 59),
        extracted_payload={"body_fetched": True, "title_category": "lottery_active"},
    )
    await svc.apply(c, now=datetime(2026, 4, 21, 12))
    notifier = FakeNotifier()
    disp = NotificationDispatcher(
        lottery_repo=LotteryEventRepo(db),
        product_repo=ProductRepo(db),
        notification_repo=NotificationRepo(db),
        notifier=notifier,
    )
    result = await disp.dispatch(now=datetime(2026, 4, 21, 12))
    assert result.new_sent == 0
    assert result.skipped_low_confidence >= 1


@pytest.mark.asyncio
async def test_dispatch_filters_out_old_events(db):
    """first_seen_at が fresh_window より古い event は通知対象外。"""
    await _seed_source(db)
    # event を直接 insert し、first_seen_at を過去にセット
    async with db.pool.acquire() as conn:
        # sources テーブルに 1 レコード必要
        pass
    lrepo = LotteryEventRepo(db)
    old_id = await lrepo.create(
        retailer_name="pokemoncenter_online",
        canonical_title="old announcement",
        sales_type="lottery",
        dedupe_key="old-k1",
        apply_start_at=datetime(2026, 1, 10, 14),
        apply_end_at=datetime(2026, 1, 14, 23, 59),
        source_primary_url="https://old",
        confidence_score=95,
        official_confirmation_status="confirmed",
        status="active",
    )
    # first_seen_at を 10 日前にセット
    async with db.pool.acquire() as conn:
        await conn.execute(
            "UPDATE lottery_events SET first_seen_at = $1 WHERE id = $2",
            datetime(2026, 4, 11, 12), old_id,
        )
    notifier = FakeNotifier()
    disp = NotificationDispatcher(
        lottery_repo=lrepo,
        product_repo=ProductRepo(db),
        notification_repo=NotificationRepo(db),
        notifier=notifier,
        max_per_run=10,
        max_per_day=150,
        fresh_window=timedelta(days=3),
    )
    result = await disp.dispatch(now=datetime(2026, 4, 21, 12))
    assert result.new_sent == 0
    assert notifier.sent == []


@pytest.mark.asyncio
async def test_dispatch_skips_unknown_sales_type(db):
    """sales_type=unknown は pending_review になり、active list に載らない → 送られない。"""
    await _seed_source(db)
    svc = LotteryEventUpsertService(
        lottery_repo=LotteryEventRepo(db),
        product_repo=ProductRepo(db),
        source_repo=SourceRepo(db),
    )
    c = Candidate(
        product_name_raw="pXYZ", product_name_normalized="pXYZ",
        retailer_name="pokemoncenter_online", sales_type="unknown",
        canonical_title="t", source_name="pokemon_official_news",
        source_url="https://x", source_title="t", raw_snapshot="h",
        apply_start_at=datetime(2026, 5, 10, 14),
        apply_end_at=datetime(2026, 5, 14, 23, 59),
        extracted_payload={"body_fetched": True, "title_category": "sales_method"},
    )
    await svc.apply(c, now=datetime(2026, 4, 21, 12))
    notifier = FakeNotifier()
    disp = NotificationDispatcher(
        lottery_repo=LotteryEventRepo(db),
        product_repo=ProductRepo(db),
        notification_repo=NotificationRepo(db),
        notifier=notifier,
    )
    result = await disp.dispatch(now=datetime(2026, 4, 21, 12))
    assert result.new_sent == 0
    assert notifier.sent == []


@pytest.mark.asyncio
async def test_dispatch_updates_fires_for_extended_event(db):
    """new 通知送信済 event の significant field が変化 → update 通知が発火。"""
    eid = await _create_confirmed_event(db)
    notifier = FakeNotifier()
    disp = NotificationDispatcher(
        lottery_repo=LotteryEventRepo(db),
        product_repo=ProductRepo(db),
        notification_repo=NotificationRepo(db),
        notifier=notifier,
        max_per_run=10,
        max_per_day=150,
    )
    # 先に new 通知を発火
    r_new = await disp.dispatch(now=datetime(2026, 4, 21, 12, 5))
    assert r_new.new_sent == 1
    # event の apply_end_at を延長 (意味差分)
    await LotteryEventRepo(db).update(
        eid,
        apply_end_at=datetime(2026, 5, 20, 23, 59),
    )
    # update 通知 dispatch (new 送信後 7時間以上経過 = UPDATE_COOLDOWN 超え)
    result = await disp.dispatch_updates(now=datetime(2026, 4, 21, 19, 10))
    assert result.update_sent == 1


@pytest.mark.asyncio
async def test_dispatch_updates_skips_without_prior_new(db):
    """new 通知未送信の event には update 通知を送らない。"""
    eid = await _create_confirmed_event(db)
    # new 通知は送らない
    notifier = FakeNotifier()
    disp = NotificationDispatcher(
        lottery_repo=LotteryEventRepo(db),
        product_repo=ProductRepo(db),
        notification_repo=NotificationRepo(db),
        notifier=notifier,
        max_per_run=10,
        max_per_day=150,
    )
    # update だけ呼ぶ
    await LotteryEventRepo(db).update(
        eid, apply_end_at=datetime(2026, 5, 20, 23, 59),
    )
    result = await disp.dispatch_updates(now=datetime(2026, 4, 21, 12, 10))
    assert result.update_sent == 0


@pytest.mark.asyncio
async def test_dispatch_deadlines_fires_when_apply_end_near(db):
    """apply_end_at が 3h 以内に迫り、new 送信済みなら deadline 通知が送られる。"""
    eid = await _create_confirmed_event(db)
    notifier = FakeNotifier()
    disp = NotificationDispatcher(
        lottery_repo=LotteryEventRepo(db),
        product_repo=ProductRepo(db),
        notification_repo=NotificationRepo(db),
        notifier=notifier,
        max_per_run=10,
        max_per_day=150,
    )
    # 先に new 通知を発火
    await disp.dispatch(now=datetime(2026, 4, 21, 12, 5))
    assert len(notifier.sent) == 1
    # apply_end_at を later の 2h後 に書き換え、later から 3h window 内で deadline 呼び出し
    later = datetime(2026, 4, 21, 14, 0)
    await LotteryEventRepo(db).update(eid, apply_end_at=later + timedelta(hours=2))
    result = await disp.dispatch_deadlines(now=later)
    assert result.update_sent == 1
    deadline_msg = notifier.sent[-1]
    assert "⏰" in deadline_msg and "締切" in deadline_msg


@pytest.mark.asyncio
async def test_dispatch_deadlines_skips_without_prior_new(db):
    """new が未送信の event には deadline も送らない (順序保証)。"""
    eid = await _create_confirmed_event(db)
    notifier = FakeNotifier()
    disp = NotificationDispatcher(
        lottery_repo=LotteryEventRepo(db),
        product_repo=ProductRepo(db),
        notification_repo=NotificationRepo(db),
        notifier=notifier,
    )
    later = datetime(2026, 4, 21, 14, 0)
    await LotteryEventRepo(db).update(eid, apply_end_at=later + timedelta(hours=2))
    result = await disp.dispatch_deadlines(now=later)
    assert result.update_sent == 0
    assert notifier.sent == []


@pytest.mark.asyncio
async def test_dispatch_deadlines_dedup_within_window(db):
    """同一 event の deadline 通知は dedupe_key で 1 回だけ送信される。"""
    eid = await _create_confirmed_event(db)
    notifier = FakeNotifier()
    disp = NotificationDispatcher(
        lottery_repo=LotteryEventRepo(db),
        product_repo=ProductRepo(db),
        notification_repo=NotificationRepo(db),
        notifier=notifier,
    )
    await disp.dispatch(now=datetime(2026, 4, 21, 12, 5))
    later = datetime(2026, 4, 21, 14, 0)
    await LotteryEventRepo(db).update(eid, apply_end_at=later + timedelta(hours=2))
    r1 = await disp.dispatch_deadlines(now=later)
    r2 = await disp.dispatch_deadlines(now=later + timedelta(minutes=30))
    assert r1.update_sent == 1
    assert r2.update_sent == 0
    assert r2.suppressed == 1


def test_format_event_message_has_label():
    from pokebot.storage.repos import LotteryEvent

    ev = LotteryEvent(
        id=1,
        product_id=None,
        retailer_name="pokemoncenter_online",
        store_name=None,
        canonical_title="アビスアイ抽選",
        sales_type="lottery",
        apply_start_at=datetime(2026, 5, 10, 14),
        apply_end_at=datetime(2026, 5, 14, 23, 59),
        result_at=datetime(2026, 5, 16, 11),
        purchase_start_at=None,
        purchase_end_at=None,
        purchase_limit_text="1人1回",
        conditions_text=None,
        source_primary_url="https://ex",
        official_confirmation_status="confirmed",
        confidence_score=95,
        dedupe_key="k1",
        status="active",
        first_seen_at=datetime(2026, 4, 21),
        last_seen_at=datetime(2026, 4, 21),
    )
    msg = format_event_message(ev, source_note="ポケモン公式")
    assert "[高信頼]" in msg
    assert "抽選受付中" in msg
    assert "5/10 14:00" in msg
    assert "5/14 23:59" in msg
    assert "5/16 11:00" in msg
