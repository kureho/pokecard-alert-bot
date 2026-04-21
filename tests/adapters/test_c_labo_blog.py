from pathlib import Path

import pytest

from pokebot.adapters.c_labo_blog import CLaboBlogAdapter


@pytest.mark.asyncio
async def test_c_labo_extracts_pokemon_lottery_entries():
    """実データ fixture で抽出ロジックが壊れていないことを確認。

    fixture はスナップショットなので Tokyo-metro 店舗のポケカ抽選記事が
    たまたま 0 件のこともある (地方店舗の投稿が主)。残った候補は必ず
    Tokyo-metro 店舗で、ポケカ関連タイトルである。
    """
    html = Path("tests/fixtures/c_labo_blog.html").read_text(encoding="utf-8")
    adapter = CLaboBlogAdapter(html=html)
    candidates = await adapter.run()
    tokyo_metro_stores = {
        "カードラボ秋葉原",
        "カードラボ秋葉原2号店",
        "カードラボ新宿",
        "カードラボ池袋",
        "カードラボ渋谷",
        "カードラボ横浜",
        "カードラボ所沢",
        "カードラボ津田沼",
    }
    for c in candidates:
        assert c.retailer_name == "cardlabo"
        assert c.source_name == "c_labo_blog"
        assert c.store_name in tokyo_metro_stores
        assert "ポケモン" in c.canonical_title or "ポケカ" in c.canonical_title


@pytest.mark.asyncio
async def test_c_labo_filters_non_pokemon():
    html = """<html><body>
      <a class="js-targetLink" href="/shop/shinjuku/blog/1/" title="【遊戯王】デッキ紹介">yugioh</a>
      <a class="js-targetLink" href="/shop/shinjuku/blog/2/" title="【ポケモンカード】アビスアイ抽選販売のお知らせ">poke</a>
    </body></html>"""
    adapter = CLaboBlogAdapter(html=html)
    candidates = await adapter.run()
    assert len(candidates) == 1
    assert "アビスアイ" in candidates[0].canonical_title
    assert candidates[0].store_name == "カードラボ新宿"


@pytest.mark.asyncio
async def test_c_labo_filters_out_non_tokyo_metro_shops():
    """東京近郊 (1都3県) 以外の店舗 slug は candidate に載せない。

    ユーザーが通知を受けたい地域外 (浜松・名古屋・大阪・福岡等) を adapter 層で
    弾くことで、body fetch 数も減り DB にも残らない。
    """
    html = """<html><body>
      <a class="js-targetLink" href="/shop/hamamatsu/blog/1/" title="【ポケモンカード】アビスアイ抽選販売のお知らせ">h</a>
      <a class="js-targetLink" href="/shop/nagoya/blog/2/" title="【ポケモンカード】アビスアイ抽選販売のお知らせ">n</a>
      <a class="js-targetLink" href="/shop/osaka/blog/3/" title="【ポケモンカード】アビスアイ抽選販売のお知らせ">o</a>
      <a class="js-targetLink" href="/shop/akihabara/blog/4/" title="【ポケモンカード】アビスアイ抽選販売のお知らせ">a</a>
      <a class="js-targetLink" href="/shop/tokorozawa/blog/5/" title="【ポケモンカード】アビスアイ抽選販売のお知らせ">t</a>
      <a class="js-targetLink" href="/shop/tsudanuma/blog/6/" title="【ポケモンカード】アビスアイ抽選販売のお知らせ">ts</a>
    </body></html>"""
    adapter = CLaboBlogAdapter(html=html)
    candidates = await adapter.run()
    stores = {c.store_name for c in candidates}
    # 1都3県の 3 店舗のみ残る
    assert stores == {"カードラボ秋葉原", "カードラボ所沢", "カードラボ津田沼"}
    # 浜松・名古屋・大阪は完全に除外
    for s in stores:
        assert "浜松" not in s and "名古屋" not in s and "大阪" not in s


@pytest.mark.asyncio
async def test_c_labo_unknown_slug_is_filtered_out():
    """知らない slug は保守的に除外 (誤って地方店舗を通知しない)。"""
    html = """<html><body>
      <a class="js-targetLink" href="/shop/newshop/blog/99/" title="【ポケモンカード】アビスアイ抽選販売のお知らせ">x</a>
    </body></html>"""
    adapter = CLaboBlogAdapter(html=html)
    candidates = await adapter.run()
    assert candidates == []


@pytest.mark.asyncio
async def test_c_labo_strips_announcement_suffix():
    html = """<html><body>
      <a class="js-targetLink" href="/shop/akihabara/blog/1/" title="【5/22発売】 ポケモンカードゲーム MEGA 拡張パック アビスアイ抽選予約・販売のお知らせ">a</a>
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
