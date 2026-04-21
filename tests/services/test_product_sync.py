import pytest

from pokebot.adapters.base import Candidate
from pokebot.services.product_sync import ProductSyncService
from pokebot.storage.repos import ProductRepo


@pytest.mark.asyncio
async def test_hint_upserts_into_products(db):
    repo = ProductRepo(db)
    svc = ProductSyncService(repo)
    candidates = [
        Candidate(
            product_name_raw="拡張パック アビスアイ", product_name_normalized="アビスアイ",
            retailer_name="pokemon_official", sales_type="unknown",
            canonical_title="拡張パック アビスアイ が 2026年5月22日 に発売",
            source_name="pokemon_official_products",
            source_url="https://www.pokemon-card.com/ex/m5/",
            source_title="拡張パック アビスアイ",
            raw_snapshot="hash1",
            extracted_payload={
                "is_product_master_hint": True,
                "release_date": "2026-05-22",
                "product_type": "拡張パック",
                "official_product_url": "https://www.pokemon-card.com/ex/m5/",
            },
        )
    ]
    count = await svc.apply(candidates)
    assert count == 1
    p = await repo.find_by_normalized("アビスアイ")
    assert p and p.canonical_name == "拡張パック アビスアイ"
    assert str(p.release_date) == "2026-05-22"


@pytest.mark.asyncio
async def test_non_hint_candidates_ignored(db):
    repo = ProductRepo(db)
    svc = ProductSyncService(repo)
    c = Candidate(
        product_name_raw="x", product_name_normalized="x",
        retailer_name="r", sales_type="lottery",
        canonical_title="x", source_name="y", source_url="z",
        source_title="x", raw_snapshot="h",
        extracted_payload={},  # no hint flag
    )
    assert await svc.apply([c]) == 0
