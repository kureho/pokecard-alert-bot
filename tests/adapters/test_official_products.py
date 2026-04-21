from pathlib import Path

import pytest

from pokebot.adapters.official_products import PokemonOfficialProductsAdapter


@pytest.mark.asyncio
async def test_official_products_extracts_release_hints():
    html = Path("tests/fixtures/pokemon_official_news.html").read_text(encoding="utf-8")
    adapter = PokemonOfficialProductsAdapter(html=html)
    candidates = await adapter.run()
    # アビスアイ or 似た発売告知が1件以上
    assert len(candidates) >= 1
    for c in candidates:
        assert c.extracted_payload.get("is_product_master_hint") is True
        assert c.product_name_normalized
        assert c.source_url.startswith("https://www.pokemon-card.com")
