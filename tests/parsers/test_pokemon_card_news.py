from pathlib import Path

import pytest
from pokebot.parsers.pokemon_card_news import news_list


@pytest.mark.asyncio
async def test_news_list_extracts_entries():
    html = Path("tests/fixtures/pokemon_card_news.html").read_text(encoding="utf-8")
    items = await news_list(html)
    assert len(items) >= 3
    assert all(i.source == "pokemon_card_news" for i in items)
    assert all(i.url.startswith("https://www.pokemon-card.com") for i in items)
    assert all(i.kind_hint in {"announcement", "new_product"} for i in items)


@pytest.mark.asyncio
async def test_new_product_hint_detected_by_keyword():
    html = Path("tests/fixtures/pokemon_card_news.html").read_text(encoding="utf-8")
    items = await news_list(html)
    new_products = [i for i in items if i.kind_hint == "new_product"]
    for i in new_products:
        assert any(k in i.raw_title for k in ("発売", "新弾", "拡張パック", "ハイクラス"))
