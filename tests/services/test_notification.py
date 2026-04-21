from datetime import datetime

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
            product_name_raw=f"p{i}",
            product_name_normalized=f"p{i}",
            retailer_name="pokemoncenter_online",
            sales_type="lottery",
            canonical_title=f"t{i}",
            source_name="pokemon_official_news",
            source_url=f"https://ex.com/{i}",
            source_title=f"t{i}",
            raw_snapshot=f"h{i}",
            apply_start_at=datetime(2026, 5, 10, 14),
            apply_end_at=datetime(2026, 5, 14, 23, 59),
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
        product_name_raw="p",
        product_name_normalized="p",
        retailer_name="unknown",
        sales_type="unknown",
        canonical_title="t",
        source_name="low_trust",
        source_url="https://x",
        source_title="t",
        raw_snapshot="h",
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
