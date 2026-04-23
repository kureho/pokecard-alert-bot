"""google_news_rss adapter のフィルタリング / domain 判定 / body 抽出の検証。

Google News redirect 解決は実 HTTP を発生させないよう fake resolver を使う。
"""

from __future__ import annotations

import pytest

from pokebot.adapters.google_news_rss import (
    ALLOWED_DOMAINS,
    EXCLUDED_DOMAINS,
    GoogleNewsRssAdapter,
)


def _feed(entries: list[tuple[str, str]]) -> str:
    """RSS feed XML を組み立て。entries = [(title, link), ...]。"""
    items = "".join(
        f"<item><title>{t}</title><link>{ln}</link></item>" for t, ln in entries
    )
    return (
        '<?xml version="1.0"?><rss version="2.0"><channel>' + items + "</channel></rss>"
    )


def _make_resolver(mapping: dict[str, str]):
    async def _resolve(url: str) -> str:
        return mapping.get(url, url)
    return _resolve


def _make_body_fetcher(html_by_url: dict[str, str]):
    async def _fetch(url: str) -> str:
        return html_by_url.get(
            url,
            "<html><body>抽選販売を実施します。応募期間: 5月10日 14:00 〜 5月14日 23:59</body></html>",
        )
    return _fetch


# ===== 基本動作 =====


@pytest.mark.asyncio
async def test_allowed_domain_creates_candidate():
    """allowlist に含まれる domain は candidate 化される。"""
    xml = _feed([
        ("【トイザらス】ポケモンカード抽選販売のお知らせ", "https://news.google.com/articles/a1"),
    ])
    resolver = _make_resolver({
        "https://news.google.com/articles/a1": "https://www.toysrus.co.jp/ja-jp/lottery/123.html",
    })
    adapter = GoogleNewsRssAdapter(
        xml=xml, redirect_resolver=resolver, body_fetcher=_make_body_fetcher({}),
    )
    candidates = await adapter.run()
    assert len(candidates) == 1
    c = candidates[0]
    assert c.retailer_name == "toysrus"
    assert c.source_url == "https://www.toysrus.co.jp/ja-jp/lottery/123.html"
    assert c.sales_type == "lottery"  # body に「抽選」あり
    assert c.evidence_type == "store_notice"


@pytest.mark.asyncio
async def test_excluded_domain_is_skipped():
    """EXCLUDED_DOMAINS (voice.pokemon 等) は既存 adapter がカバーするため skip。"""
    xml = _feed([
        ("ポケモンセンターメガトウキョー抽選販売のお知らせ", "https://news.google.com/articles/a1"),
    ])
    resolver = _make_resolver({
        "https://news.google.com/articles/a1": "https://voice.pokemon.co.jp/stv/megatokyo/x.html",
    })
    adapter = GoogleNewsRssAdapter(
        xml=xml, redirect_resolver=resolver, body_fetcher=_make_body_fetcher({}),
    )
    candidates = await adapter.run()
    assert candidates == []


@pytest.mark.asyncio
async def test_unknown_domain_is_skipped():
    """allowlist 外の domain は skip (質優先 whitelist 方式)。"""
    xml = _feed([
        ("まとめ系サイトのポケカ抽選記事", "https://news.google.com/articles/a1"),
        # "まとめ" キーワードで先に弾かれるので、allowlist 外判定まで到達しない記事も混ぜる
        ("【pokeNEWS】ポケモンカード抽選受付", "https://news.google.com/articles/a2"),
    ])
    resolver = _make_resolver({
        "https://news.google.com/articles/a1": "https://pokecawatch.com/xx/",
        "https://news.google.com/articles/a2": "https://pokecanews.jp/yy/",
    })
    adapter = GoogleNewsRssAdapter(
        xml=xml, redirect_resolver=resolver, body_fetcher=_make_body_fetcher({}),
    )
    candidates = await adapter.run()
    assert candidates == []


# ===== title フィルタ =====


@pytest.mark.asyncio
async def test_summary_article_is_skipped():
    """タイトルに「まとめ」「一覧」等を含む記事は、allowlist 内でも skip。"""
    xml = _feed([
        ("【ポケカ】アビスアイの予約・抽選情報まとめ", "https://news.google.com/articles/a1"),
        ("ポケモンカード抽選販売一覧", "https://news.google.com/articles/a2"),
    ])
    resolver = _make_resolver({
        "https://news.google.com/articles/a1": "https://www.toysrus.co.jp/x1.html",
        "https://news.google.com/articles/a2": "https://www.hmv.co.jp/x2.html",
    })
    adapter = GoogleNewsRssAdapter(
        xml=xml, redirect_resolver=resolver, body_fetcher=_make_body_fetcher({}),
    )
    candidates = await adapter.run()
    assert candidates == []


@pytest.mark.asyncio
async def test_no_pokemon_keyword_skipped():
    """ポケモン関連キーワードがない記事は skip。"""
    xml = _feed([
        ("アニメグッズ抽選販売", "https://news.google.com/articles/a1"),
    ])
    resolver = _make_resolver({
        "https://news.google.com/articles/a1": "https://www.toysrus.co.jp/x.html",
    })
    adapter = GoogleNewsRssAdapter(
        xml=xml, redirect_resolver=resolver, body_fetcher=_make_body_fetcher({}),
    )
    candidates = await adapter.run()
    assert candidates == []


@pytest.mark.asyncio
async def test_no_lottery_keyword_skipped():
    """抽選/予約/応募/受付を含まない記事は skip。"""
    xml = _feed([
        ("ポケモンカード新商品発売", "https://news.google.com/articles/a1"),
    ])
    resolver = _make_resolver({
        "https://news.google.com/articles/a1": "https://www.toysrus.co.jp/x.html",
    })
    adapter = GoogleNewsRssAdapter(
        xml=xml, redirect_resolver=resolver, body_fetcher=_make_body_fetcher({}),
    )
    candidates = await adapter.run()
    assert candidates == []


@pytest.mark.asyncio
async def test_past_event_title_is_skipped():
    """当選者発表・応募終了などの過去イベ系は classify_title で skip。"""
    xml = _feed([
        ("【トイザらス】ポケモンカード抽選当選者発表のお知らせ", "https://news.google.com/articles/a1"),
    ])
    resolver = _make_resolver({
        "https://news.google.com/articles/a1": "https://www.toysrus.co.jp/x.html",
    })
    adapter = GoogleNewsRssAdapter(
        xml=xml, redirect_resolver=resolver, body_fetcher=_make_body_fetcher({}),
    )
    candidates = await adapter.run()
    assert candidates == []


# ===== sales_type 判別 =====


@pytest.mark.asyncio
async def test_body_determines_sales_type_when_title_unknown():
    """title に sales_type 明示がなくても body から先着を読み取れる。"""
    xml = _feed([
        ("【Joshin】ポケモンカード受付のお知らせ", "https://news.google.com/articles/a1"),
    ])
    resolver = _make_resolver({
        "https://news.google.com/articles/a1": "https://shop.joshin.co.jp/pokemon/x.html",
    })
    body = "<html><body><p>先着順で販売します。5月22日14:00から。</p></body></html>"
    adapter = GoogleNewsRssAdapter(
        xml=xml, redirect_resolver=resolver,
        body_fetcher=_make_body_fetcher(
            {"https://shop.joshin.co.jp/pokemon/x.html": body}
        ),
    )
    candidates = await adapter.run()
    assert len(candidates) == 1
    assert candidates[0].sales_type == "first_come"
    assert candidates[0].retailer_name == "joshin"


@pytest.mark.asyncio
async def test_body_sales_type_unknown_skips_candidate():
    """body に抽選/先着/整理券/招待 いずれもない → candidate 発行しない (ノイズ排除)。"""
    xml = _feed([
        ("【GEO】ポケモンカード受付", "https://news.google.com/articles/a1"),
    ])
    resolver = _make_resolver({
        "https://news.google.com/articles/a1": "https://ec.geo-online.co.jp/x.html",
    })
    body = "<html><body><p>新商品を案内します。5月22日発売。</p></body></html>"
    adapter = GoogleNewsRssAdapter(
        xml=xml, redirect_resolver=resolver,
        body_fetcher=_make_body_fetcher({"https://ec.geo-online.co.jp/x.html": body}),
    )
    candidates = await adapter.run()
    assert candidates == []


# ===== 静的検査 =====


def test_allowed_and_excluded_domains_dont_overlap():
    """ALLOWED と EXCLUDED は重なってはならない (設計ミス検知)。"""
    overlap = set(ALLOWED_DOMAINS.keys()) & EXCLUDED_DOMAINS
    assert overlap == set(), f"allowlist と excluded が重複: {overlap}"


def test_allowed_domains_contains_expected_retailers():
    """poke-price の店舗リストから最低限拾いたい retailer が allowlist に入っている。"""
    expected_retailers = {
        "toysrus", "hmv", "joshin", "geo", "seven_net", "aeon", "snkrdunk",
    }
    actual = set(ALLOWED_DOMAINS.values())
    missing = expected_retailers - actual
    assert missing == set(), f"allowlist に必要な retailer が不足: {missing}"
