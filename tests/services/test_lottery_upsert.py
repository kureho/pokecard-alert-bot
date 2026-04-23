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
        extracted_payload={"body_fetched": True, "title_category": "lottery_active"},
        # Dispatch1: evidence 層。pokemon_official_news は official_notice 相当。
        evidence_type="official_notice",
        application_url="https://www.pokemon-card.com/info/1",
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
    # Dispatch1: evidence_type=official_notice + 主要情報揃い → confirmed_strong
    ev = await LotteryEventRepo(db).find_by_dedupe_key(out.dedupe_key)
    assert ev.official_confirmation_status == "confirmed"
    assert ev.confidence_level == "confirmed_strong"
    assert ev.confidence_score >= 85


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
async def test_apply_end_at_past_is_archived_on_create(db):
    """apply_end_at が 1h 以上過去の新規 candidate は archived で保存 (通知対象外)。"""
    from datetime import timedelta
    svc = await _setup(db)
    now = datetime(2026, 4, 21, 12)
    ended = _cand(
        product_name_normalized="終了告知",
        apply_start_at=now - timedelta(days=5),
        apply_end_at=now - timedelta(hours=2),
    )
    ended.source_published_at = now - timedelta(days=3)  # fresh enough
    out = await svc.apply(ended, now=now)
    assert out and out.is_new
    events = await LotteryEventRepo(db).list_active(limit=100)
    assert out.event_id not in {e.id for e in events}


@pytest.mark.asyncio
async def test_apply_end_at_within_grace_stays_active(db):
    """apply_end_at が 1h 以内なら active のまま (境界の 1h grace)。"""
    from datetime import timedelta
    svc = await _setup(db)
    now = datetime(2026, 4, 21, 12)
    just_ended = _cand(
        product_name_normalized="直前終了",
        apply_start_at=now - timedelta(days=5),
        apply_end_at=now - timedelta(minutes=30),
    )
    just_ended.source_published_at = now - timedelta(days=1)
    out = await svc.apply(just_ended, now=now)
    assert out and out.is_new
    events = await LotteryEventRepo(db).list_active(limit=100)
    assert out.event_id in {e.id for e in events}


@pytest.mark.asyncio
async def test_existing_active_event_archived_when_apply_end_passes(db):
    """既存 active event が再観測時に apply_end_at 過去判定で archived に遷移する。"""
    from datetime import timedelta
    svc = await _setup(db)
    now = datetime(2026, 4, 21, 12)
    # 最初は apply 受付中として登録 (apply_end_at を now+1d に上書き)
    ongoing = _cand(
        apply_start_at=now - timedelta(days=1),
        apply_end_at=now + timedelta(days=1),
    )
    ongoing.source_published_at = now - timedelta(days=1)
    o1 = await svc.apply(ongoing, now=now)
    assert o1.is_new
    events = await LotteryEventRepo(db).list_active(limit=100)
    assert o1.event_id in {e.id for e in events}

    # 時間経過: 受付終了から 3h 経過した now で再観測 (同じ candidate)
    later_now = now + timedelta(days=1, hours=3)
    await svc.apply(ongoing, now=later_now)
    events2 = await LotteryEventRepo(db).list_active(limit=100)
    assert o1.event_id not in {e.id for e in events2}


@pytest.mark.asyncio
async def test_unknown_sales_type_is_pending_review(db):
    """sales_type=unknown は status=pending_review で active list に載らない。"""
    svc = await _setup(db)
    now = datetime(2026, 4, 21, 12)
    c = _cand(sales_type="unknown")
    out = await svc.apply(c, now=now)
    assert out and out.is_new
    # status='pending_review' で active list に載らない
    events = await LotteryEventRepo(db).list_active(limit=100)
    assert out.event_id not in {e.id for e in events}


@pytest.mark.asyncio
async def test_cross_source_corroboration_boosts_confidence(db):
    """同一 product が 2 ソースで検出 → +15 ボーナスで confidence 上昇。"""
    # 2 つの source を登録: 公式 (trust=100) と Twitter (trust=80)
    srepo = SourceRepo(db)
    await srepo.upsert(
        source_name="pokemon_official_news", source_type="official_news",
        base_url="https://x", trust_score=100,
    )
    await srepo.upsert(
        source_name="twitter_pokecayoyaku", source_type="social",
        base_url="https://y", trust_score=80,
    )
    svc = LotteryEventUpsertService(
        lottery_repo=LotteryEventRepo(db),
        product_repo=ProductRepo(db),
        source_repo=srepo,
    )
    now = datetime(2026, 4, 21, 12)

    # 1件目: 公式ソース側で product=アビスアイ
    c1 = _cand(
        product_name_normalized="アビスアイ",
        source_name="pokemon_official_news",
        source_url="https://pokemon-card.com/a",
        raw_snapshot="h-official",
    )
    out1 = await svc.apply(c1, now=now)
    assert out1 and out1.is_new

    # 2件目: Twitter 側で別 retailer/store。product + 応募期間が同じなので、
    # content_dedupe_key ベースで既存 event に統合される (is_new=False)。
    c2 = _cand(
        product_name_normalized="アビスアイ",
        retailer_name="amazon",
        store_name="@pokecayoyaku",
        source_name="twitter_pokecayoyaku",
        source_url="https://twitter.com/x/status/1",
        raw_snapshot="h-twitter",
        evidence_type="social_post",
        application_url=None,
    )
    out2 = await svc.apply(c2, now=now)
    # 同一 event への統合: is_new=False、source link は追加されている。
    assert out2 and not out2.is_new
    assert out2.event_id == out1.event_id
    # 2 つの異なる source_id が event_sources に紐付いていることを確認
    cnt = await LotteryEventRepo(db).count_distinct_sources_for_product("アビスアイ")
    assert cnt == 2
    # 既存 event の confidence_level は official 側の confirmed_strong を維持
    ev1 = await LotteryEventRepo(db).find_by_dedupe_key(out1.dedupe_key)
    assert ev1.confidence_level == "confirmed_strong"


@pytest.mark.asyncio
async def test_count_distinct_sources_returns_zero_for_empty(db):
    """product_name_normalized が None/空 なら 0。"""
    repo = LotteryEventRepo(db)
    assert await repo.count_distinct_sources_for_product(None) == 0
    assert await repo.count_distinct_sources_for_product("") == 0


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


# ===== Dispatch1: evidence 層 =====


@pytest.mark.asyncio
async def test_upsert_sets_confidence_level_confirmed_strong(db):
    """official_notice + 主要情報揃い → confidence_level=confirmed_strong。"""
    svc = await _setup(db)
    now = datetime(2026, 4, 21, 12)
    out = await svc.apply(_cand(), now=now)
    ev = await LotteryEventRepo(db).find_by_dedupe_key(out.dedupe_key)
    assert ev.confidence_level == "confirmed_strong"
    assert ev.official_confirmation_status == "confirmed"
    assert ev.evidence_score is not None
    assert ev.evidence_summary and "抽選受付" in ev.evidence_summary or "公式告知" in ev.evidence_summary
    # evidence 層の URL が保存される
    assert ev.application_url == "https://www.pokemon-card.com/info/1"


@pytest.mark.asyncio
async def test_upsert_social_post_becomes_candidate_level(db):
    """Twitter 相当 (social_post) は candidate 止まり。legacy status=unconfirmed。"""
    await SourceRepo(db).upsert(
        source_name="twitter_x", source_type="social",
        base_url="https://y", trust_score=80,
    )
    svc = LotteryEventUpsertService(
        lottery_repo=LotteryEventRepo(db),
        product_repo=ProductRepo(db),
        source_repo=SourceRepo(db),
    )
    c = _cand(
        source_name="twitter_x",
        evidence_type="social_post",
        application_url=None,
    )
    out = await svc.apply(c, now=datetime(2026, 4, 21, 12))
    ev = await LotteryEventRepo(db).find_by_dedupe_key(out.dedupe_key)
    assert ev.confidence_level == "candidate"
    assert ev.official_confirmation_status == "unconfirmed"


@pytest.mark.asyncio
async def test_upsert_sale_status_inferred_from_time_axis(db):
    """now < apply_start_at → sale_status='upcoming'。"""
    svc = await _setup(db)
    now = datetime(2026, 4, 21, 12)
    # _cand() の apply_start_at は 2026/5/10 14:00 なので now より未来 = upcoming
    out = await svc.apply(_cand(), now=now)
    ev = await LotteryEventRepo(db).find_by_dedupe_key(out.dedupe_key)
    assert ev.sale_status == "upcoming"


@pytest.mark.asyncio
async def test_upsert_sale_status_accepting_when_inside_window(db):
    """apply_start_at <= now <= apply_end_at → accepting。"""
    svc = await _setup(db)
    during = datetime(2026, 5, 12, 10)  # within apply window
    out = await svc.apply(_cand(), now=during)
    ev = await LotteryEventRepo(db).find_by_dedupe_key(out.dedupe_key)
    assert ev.sale_status == "accepting"


@pytest.mark.asyncio
async def test_upsert_persists_page_fingerprint(db):
    svc = await _setup(db)
    now = datetime(2026, 4, 21, 12)
    out = await svc.apply(_cand(), now=now)
    ev = await LotteryEventRepo(db).find_by_dedupe_key(out.dedupe_key)
    assert ev.page_fingerprint is not None
    assert len(ev.page_fingerprint) == 32


@pytest.mark.asyncio
async def test_upsert_default_evidence_type_unknown_is_low(db):
    """evidence_type 未指定 (default 'unknown') の Candidate は candidate 相当 = 通知対象外。"""
    svc = await _setup(db)
    now = datetime(2026, 4, 21, 12)
    # evidence_type を明示的に unknown にセット
    c = _cand(evidence_type="unknown", application_url=None)
    out = await svc.apply(c, now=now)
    ev = await LotteryEventRepo(db).find_by_dedupe_key(out.dedupe_key)
    assert ev.confidence_level == "candidate"
