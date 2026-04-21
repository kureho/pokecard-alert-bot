from pathlib import Path

import pytest

from pokebot.adapters.c_labo_blog import CLaboBlogAdapter


@pytest.mark.asyncio
async def test_c_labo_extracts_pokemon_lottery_entries():
    html = Path("tests/fixtures/c_labo_blog.html").read_text(encoding="utf-8")
    adapter = CLaboBlogAdapter(html=html)
    candidates = await adapter.run()
    # fixture には「アビスアイ抽選販売のお知らせ」等が含まれる想定
    assert len(candidates) >= 1
    for c in candidates:
        assert c.retailer_name == "cardlabo"
        assert c.store_name and "カードラボ" in c.store_name
        assert c.source_name == "c_labo_blog"
        # 「ポケモン」「ポケカ」 タイトルだけが残る
        assert "ポケモン" in c.canonical_title or "ポケカ" in c.canonical_title


@pytest.mark.asyncio
async def test_c_labo_filters_non_pokemon():
    html = """<html><body>
      <a class="js-targetLink" href="/shop/x/blog/1/" title="【遊戯王】デッキ紹介">yugioh</a>
      <a class="js-targetLink" href="/shop/gifu/blog/2/" title="【ポケモンカード】アビスアイ抽選販売のお知らせ">poke</a>
    </body></html>"""
    adapter = CLaboBlogAdapter(html=html)
    candidates = await adapter.run()
    assert len(candidates) == 1
    assert "アビスアイ" in candidates[0].canonical_title
    assert candidates[0].store_name == "カードラボ岐阜"


@pytest.mark.asyncio
async def test_c_labo_unknown_slug_falls_back():
    html = """<html><body>
      <a class="js-targetLink" href="/shop/newshop/blog/99/" title="【ポケモンカード】アビスアイ抽選販売のお知らせ">x</a>
    </body></html>"""
    adapter = CLaboBlogAdapter(html=html)
    candidates = await adapter.run()
    assert len(candidates) == 1
    assert "カードラボ(newshop)" in candidates[0].store_name


@pytest.mark.asyncio
async def test_c_labo_strips_announcement_suffix():
    html = """<html><body>
      <a class="js-targetLink" href="/shop/gifu/blog/1/" title="【5/22発売】 ポケモンカードゲーム MEGA 拡張パック アビスアイ抽選予約・販売のお知らせ">a</a>
    </body></html>"""
    adapter = CLaboBlogAdapter(html=html)
    candidates = await adapter.run()
    assert len(candidates) == 1
    c = candidates[0]
    # product_name_raw から 「抽選予約・販売のお知らせ」と「【5/22発売】」 prefix が削除されている
    assert "抽選予約・販売のお知らせ" not in c.product_name_raw
    assert "【5/22発売】" not in c.product_name_raw
    # 商品名本体は残る
    assert "アビスアイ" in c.product_name_raw
