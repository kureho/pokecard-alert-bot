from datetime import datetime, date
import pytest
from pokebot.storage.repos import (
    ProductRepo, SourceRepo, LotteryEventRepo, NotificationRepo,
)


@pytest.mark.asyncio
async def test_product_upsert_and_find(db):
    repo = ProductRepo(db)
    pid = await repo.upsert(
        canonical_name="アビスアイ", normalized_name="アビスアイ",
        release_date=date(2026, 5, 22), product_type="MEGA",
        official_product_url="https://www.pokemon-card.com/ex/m5/",
    )
    assert pid > 0
    p = await repo.find_by_normalized("アビスアイ")
    assert p and p.canonical_name == "アビスアイ"


@pytest.mark.asyncio
async def test_product_alias_resolves(db):
    repo = ProductRepo(db)
    pid = await repo.upsert(canonical_name="アビスアイ", normalized_name="アビスアイ")
    await repo.add_alias(pid, "拡張パック アビスアイ", "アビスアイ")  # same normalized_alias
    p = await repo.find_by_normalized("アビスアイ")
    assert p and p.id == pid


@pytest.mark.asyncio
async def test_source_upsert(db):
    repo = SourceRepo(db)
    sid = await repo.upsert(
        source_name="pokemon_official_products", source_type="official_product",
        base_url="https://x", trust_score=100,
    )
    assert sid > 0
    s = await repo.get_by_name("pokemon_official_products")
    assert s.trust_score == 100


@pytest.mark.asyncio
async def test_lottery_event_create_and_find(db):
    srepo = SourceRepo(db)
    sid = await srepo.upsert(
        source_name="pokemon_official_products", source_type="official_product",
        base_url="https://x", trust_score=100,
    )
    erepo = LotteryEventRepo(db)
    eid = await erepo.create(
        retailer_name="pokemoncenter_online", store_name=None,
        canonical_title="アビスアイ抽選", sales_type="lottery",
        apply_start_at=datetime(2026, 5, 10, 14),
        apply_end_at=datetime(2026, 5, 14, 23, 59),
        source_primary_url="https://ex",
        confidence_score=95, official_confirmation_status="confirmed",
        dedupe_key="アビスアイ|pokemoncenter_online|-|lottery|2026-05-10T14:00|2026-05-14T23:59",
        status="active",
    )
    ev = await erepo.find_by_dedupe_key("アビスアイ|pokemoncenter_online|-|lottery|2026-05-10T14:00|2026-05-14T23:59")
    assert ev.id == eid


@pytest.mark.asyncio
async def test_notification_try_claim_returns_none_on_duplicate(db):
    srepo = SourceRepo(db)
    await srepo.upsert(source_name="x", source_type="official_product",
                        base_url="https://x", trust_score=100)
    erepo = LotteryEventRepo(db)
    eid = await erepo.create(
        retailer_name="r", canonical_title="t", sales_type="lottery",
        dedupe_key="k1",
    )
    nrepo = NotificationRepo(db)
    first = await nrepo.try_claim(
        lottery_event_id=eid, notification_type="new", channel="line",
        dedupe_key="n1", payload_summary="x",
    )
    second = await nrepo.try_claim(
        lottery_event_id=eid, notification_type="new", channel="line",
        dedupe_key="n1", payload_summary="x",
    )
    assert first is not None
    assert second is None


@pytest.mark.asyncio
async def test_seed_sources_is_idempotent(db):
    from pokebot.seeds import seed_sources
    repo = SourceRepo(db)
    await seed_sources(repo)
    await seed_sources(repo)  # 2回目も壊れない
    sources = await repo.list_active()
    names = {s.source_name for s in sources}
    assert "pokemon_official_products" in names
    assert "pokemoncenter_store_voice" in names
    assert len(sources) >= 7
