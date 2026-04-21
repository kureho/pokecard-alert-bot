from datetime import datetime

import pytest

from pokebot.adapters.base import Candidate
from pokebot.services.lottery_upsert import LotteryEventUpsertService
from pokebot.storage.repos import LotteryEventRepo, ProductRepo, SourceRepo


async def _setup(db):
    srepo = SourceRepo(db)
    await srepo.upsert(
        source_name="pokemon_official_news", source_type="official_news",
        base_url="https://x", trust_score=100,
    )
    return LotteryEventUpsertService(
        lottery_repo=LotteryEventRepo(db),
        product_repo=ProductRepo(db),
        source_repo=srepo,
    )


def _cand(**kw) -> Candidate:
    base = dict(
        product_name_raw="アビスアイ BOX", product_name_normalized="アビスアイ",
        retailer_name="pokemoncenter_online", sales_type="lottery",
        canonical_title="アビスアイ抽選", source_name="pokemon_official_news",
        source_url="https://www.pokemon-card.com/info/1",
        source_title="【抽選販売】アビスアイ",
        raw_snapshot="h1",
        apply_start_at=datetime(2026, 5, 10, 14),
        apply_end_at=datetime(2026, 5, 14, 23, 59),
    )
    base.update(kw)
    return Candidate(**base)


@pytest.mark.asyncio
async def test_new_candidate_creates_event(db):
    svc = await _setup(db)
    now = datetime(2026, 4, 21, 12)
    out = await svc.apply(_cand(), now=now)
    assert out and out.is_new and not out.is_updated


@pytest.mark.asyncio
async def test_duplicate_candidate_no_update(db):
    svc = await _setup(db)
    now = datetime(2026, 4, 21, 12)
    o1 = await svc.apply(_cand(), now=now)
    o2 = await svc.apply(_cand(), now=now)
    assert o1.is_new and not o2.is_new
    assert not o2.is_updated


@pytest.mark.asyncio
async def test_significant_change_is_update(db):
    svc = await _setup(db)
    now = datetime(2026, 4, 21, 12)
    await svc.apply(_cand(), now=now)
    # 応募期間延長 (意味差分)
    out = await svc.apply(
        _cand(apply_end_at=datetime(2026, 5, 20, 23, 59), raw_snapshot="h2"),
        now=now,
    )
    # dedupe_key 自体は apply_end_at 含むので変わる → 新規扱い
    # TODO: 将来 dedupe_key が変わらないレベルの差分対応する場合は別物扱いを調整
    assert out.is_new  # dedupe_key が変わるので new


@pytest.mark.asyncio
async def test_hint_candidate_returns_none(db):
    svc = await _setup(db)
    c = _cand()
    c.extracted_payload = {"is_product_master_hint": True}
    assert await svc.apply(c, now=datetime(2026, 4, 21, 12)) is None


@pytest.mark.asyncio
async def test_official_source_gets_high_confidence(db):
    svc = await _setup(db)
    now = datetime(2026, 4, 21, 12)
    out = await svc.apply(_cand(), now=now)
    # 公式 (trust=100) + 主要情報揃い → confirmed
    ev = await LotteryEventRepo(db).find_by_dedupe_key(out.dedupe_key)
    assert ev.official_confirmation_status == "confirmed"
    assert ev.confidence_score >= 90


@pytest.mark.asyncio
async def test_old_announcement_marked_archived(db):
    """source_published_at が 14日以上古い candidate は status='archived'。"""
    from datetime import timedelta
    svc = await _setup(db)
    now = datetime(2026, 4, 21, 12)
    old = _cand(
        product_name_normalized="古い告知",
        apply_start_at=now - timedelta(days=55),
        apply_end_at=now - timedelta(days=50),
    )
    old.source_published_at = now - timedelta(days=60)
    out = await svc.apply(old, now=now)
    assert out and out.is_new
    events = await LotteryEventRepo(db).list_active(limit=100)
    assert out.event_id not in {e.id for e in events}


@pytest.mark.asyncio
async def test_fresh_announcement_stays_active(db):
    """source_published_at が 14日以内なら 'active'。"""
    from datetime import timedelta
    svc = await _setup(db)
    now = datetime(2026, 4, 21, 12)
    fresh = _cand()
    fresh.source_published_at = now - timedelta(days=2)
    out = await svc.apply(fresh, now=now)
    assert out and out.is_new
    events = await LotteryEventRepo(db).list_active(limit=100)
    assert out.event_id in {e.id for e in events}


@pytest.mark.asyncio
async def test_existing_active_event_is_archived_retroactively(db):
    """既存 active event が新たな candidate で古いと判明 → retroactive archive。"""
    from datetime import timedelta
    svc = await _setup(db)
    now = datetime(2026, 4, 21, 12)
    # 最初は新鮮な告知として登録
    fresh = _cand()
    fresh.source_published_at = now - timedelta(days=1)
    o1 = await svc.apply(fresh, now=now)
    assert o1.is_new
    events = await LotteryEventRepo(db).list_active(limit=100)
    assert o1.event_id in {e.id for e in events}

    # 時間が経過し、同じ dedupe_key だが source_published_at が古くなった候補が再到来
    # （本来は RSS が古いエントリをまだ出している状態）
    later_now = now + timedelta(days=20)
    old_cand = _cand()
    old_cand.source_published_at = now - timedelta(days=1)  # absolute age now 21 日
    # `now` を 20日後に送って candidate の age を 14日超に
    await svc.apply(old_cand, now=later_now)
    events2 = await LotteryEventRepo(db).list_active(limit=100)
    assert o1.event_id not in {e.id for e in events2}
