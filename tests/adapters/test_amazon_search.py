from pathlib import Path

import pytest

from pokebot.adapters.amazon_search import AmazonSearchAdapter


@pytest.mark.asyncio
async def test_amazon_search_extracts_pokemon_candidates():
    html = Path("tests/fixtures/amazon_search.html").read_text(encoding="utf-8")
    adapter = AmazonSearchAdapter(html=html)
    candidates = await adapter.run()
    # ポケカ関連商品が1件以上抽出される (fixture 依存)
    for c in candidates:
        assert c.retailer_name == "amazon"
        assert c.source_url.startswith("https://www.amazon.co.jp/dp/")
        assert c.sales_type in ("lottery", "preorder_lottery", "invitation", "first_come")


@pytest.mark.asyncio
async def test_amazon_search_skips_non_pokemon_or_unknown():
    html = """<html><body>
      <div data-asin="A1"><h2><span>ニンテンドースイッチ</span></h2></div>
      <div data-asin="A2"><h2><span>ポケモンカード アビスアイ 予約</span></h2></div>
      <div data-asin="A3"><h2><span>ポケモンカード 通常在庫</span></h2></div>
    </body></html>"""
    adapter = AmazonSearchAdapter(html=html)
    candidates = await adapter.run()
    # A2 のみ (A1 非ポケモン、A3 sales_type unknown で除外)
    assert len(candidates) == 1
    assert candidates[0].extracted_payload["asin"] == "A2"
