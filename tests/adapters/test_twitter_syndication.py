from pathlib import Path

import pytest

from pokebot.adapters.twitter_syndication import (
    TwitterPokecayoyakuAdapter,
    _detect_retailer,
    _detect_sales_type,
    _extract_product_candidate,
    _parse_tweets,
)


def test_parse_tweets_from_real_fixture():
    html = Path("tests/fixtures/twitter_pokecayoyaku.html").read_text(encoding="utf-8")
    tweets = _parse_tweets(html)
    assert len(tweets) >= 30
    # 実 fixture のトップに「アビスアイ 招待リクエスト」tweet が含まれる
    texts = [(t.get("full_text") or "") for t in tweets[:5]]
    assert any("アビスアイ" in t for t in texts)


def test_detect_sales_type_from_keywords():
    assert _detect_sales_type("招待リクエスト受付が開始しました") == "invitation"
    assert _detect_sales_type("抽選販売のお知らせ") == "lottery"
    assert _detect_sales_type("抽選予約受付中") == "preorder_lottery"
    assert _detect_sales_type("先着販売開始") == "first_come"
    assert _detect_sales_type("発売のお知らせ") == "unknown"


def test_detect_retailer_from_text():
    assert _detect_retailer("Amazonで招待リクエスト開始") == "amazon"
    assert _detect_retailer("ポケモンセンターオンラインにて抽選") == "pokemoncenter"
    assert _detect_retailer("ヨドバシ.comで販売") == "yodobashi"
    assert _detect_retailer("カードラボ渋谷で抽選") == "cardlabo"
    assert _detect_retailer("特に言及なし") == "unknown"


def test_extract_product_from_quoted_title():
    text = "Amazonで「ポケモンカードゲーム MEGA 拡張パック アビスアイ」の招待リクエスト受付が開始"
    p = _extract_product_candidate(text)
    assert "アビスアイ" in p


def test_extract_product_fallback_to_first_line():
    text = "発売日情報:\n詳細はこちら https://t.co/abc"
    p = _extract_product_candidate(text)
    assert p.startswith("発売日情報")


@pytest.mark.asyncio
async def test_adapter_run_extracts_pokemon_tweets_with_retailer():
    html = Path("tests/fixtures/twitter_pokecayoyaku.html").read_text(encoding="utf-8")
    adapter = TwitterPokecayoyakuAdapter(html=html)
    candidates = await adapter.run()
    # 1件以上、ポケモン関連ツイートが抽出される
    assert len(candidates) >= 1
    # アビスアイ tweet が含まれる
    abyss = [c for c in candidates if "アビスアイ" in c.canonical_title]
    assert abyss, f"expected abyss eye tweet, got titles={[c.canonical_title[:40] for c in candidates[:5]]}"
    c = abyss[0]
    # retailer_name に amazon が検出される
    assert c.retailer_name == "amazon"
    # sales_type が invitation
    assert c.sales_type == "invitation"
    # source_url が twitter.com
    assert c.source_url.startswith("https://twitter.com/")
    # account が store_name に入る
    assert c.store_name == "@pokecayoyaku"


def test_new_small_store_adapters_registered():
    """小規模店 4 アカウントの adapter class が正しく registry 登録されている。"""
    import pokebot.adapters  # noqa: F401 — package import triggers registrations
    from pokebot.adapters.registry import AdapterRegistry
    from pokebot.adapters.twitter_syndication import (
        TwitterBeatdownAdapter,
        TwitterTSanoTCGAdapter,
        TwitterUsagiyaJounaiAdapter,
        TwitterYsInfoAdapter,
    )

    # class の account 属性が正しい
    assert TwitterBeatdownAdapter.account == "BeatDownManager"
    assert TwitterYsInfoAdapter.account == "YS_INFO"
    assert TwitterUsagiyaJounaiAdapter.account == "usagiya_jounai"
    assert TwitterTSanoTCGAdapter.account == "T_sanoTCG"

    # registry で source_name 経由で解決できる
    for name in (
        "twitter_beatdown",
        "twitter_ys_info",
        "twitter_usagiya_jounai",
        "twitter_t_sanoTCG",
    ):
        adapter = AdapterRegistry.get(name)
        assert adapter is not None, f"adapter {name} not registered"


@pytest.mark.asyncio
async def test_adapter_filters_non_pokemon_tweets():
    # ポケモン kwなしの空 timeline fixture
    html = """<html><body>
    <script id="__NEXT_DATA__" type="application/json">
    {"props":{"pageProps":{"timeline":{"entries":[
      {"type":"tweet","content":{"tweet":{"id":"1","id_str":"1","full_text":"今日の天気","created_at":"Mon Apr 20 05:04:14 +0000 2026","permalink":"/x/status/1"}}}
    ]}}}}
    </script></body></html>"""
    adapter = TwitterPokecayoyakuAdapter(html=html)
    candidates = await adapter.run()
    assert candidates == []
