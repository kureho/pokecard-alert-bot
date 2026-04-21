from pathlib import Path

import pytest

from pokebot.adapters.pokecawatch_chusen import PokecawatchChusenAdapter


@pytest.mark.asyncio
async def test_pokecawatch_parses_entries():
    xml = Path("tests/fixtures/pokecawatch_chusen_feed.xml").read_text(encoding="utf-8")
    adapter = PokecawatchChusenAdapter(xml=xml)
    candidates = await adapter.run()
    assert len(candidates) >= 1
    for c in candidates:
        assert c.retailer_name == "pokecawatch"
        assert c.source_name == "pokecawatch_chusen"
        # utm パラメータ削除済み
        assert "?utm_" not in c.source_url
        assert "utm_source" not in c.source_url
        # sales_type が lottery / preorder_lottery / first_come のいずれか
        assert c.sales_type in (
            "lottery",
            "preorder_lottery",
            "first_come",
            "numbered_ticket",
            "invitation",
        )


@pytest.mark.asyncio
async def test_pokecawatch_strips_title_prefix_and_suffix():
    xml = Path("tests/fixtures/pokecawatch_chusen_feed.xml").read_text(encoding="utf-8")
    adapter = PokecawatchChusenAdapter(xml=xml)
    candidates = await adapter.run()
    # アビスアイが含まれるエントリが 1 件以上抽出されているはず
    assert any("アビスアイ" in c.product_name_raw for c in candidates)
    # 抽選・予約情報 suffix が product_name_raw に残っていない
    for c in candidates:
        assert "抽選・予約情報" not in c.product_name_raw
        assert "抽選予約情報" not in c.product_name_raw
        # 【ポケカ】prefix も除去されている
        assert not c.product_name_raw.startswith("【ポケカ】")


@pytest.mark.asyncio
async def test_pokecawatch_empty_entries_returns_empty():
    xml = (
        """<?xml version="1.0"?><rss version="2.0"><channel><title>empty</title></channel></rss>"""
    )
    adapter = PokecawatchChusenAdapter(xml=xml)
    candidates = await adapter.run()
    assert candidates == []
