"""rare_zaiko_aggregator adapter: フィルタ・正規化・parse 検証。"""

from __future__ import annotations

from datetime import datetime

import pytest

from pokebot.adapters.rare_zaiko_aggregator import (
    RareZaikoAggregatorAdapter,
    _extract_product_name_from_title,
    _infer_sales_type,
    _normalize_retailer,
    _parse_apply_end,
)


def _rss(items: list[tuple[str, str]]) -> str:
    """RSS (rdf) feed XML を組み立て。items = [(title, link), ...]。"""
    li = "".join(f'<rdf:li rdf:resource="{ln}" />' for _, ln in items)
    entries = "".join(
        f'<item rdf:about="{ln}"><title>{t}</title><link>{ln}</link></item>'
        for t, ln in items
    )
    return f"""<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns="http://purl.org/rss/1.0/">
  <channel><title>t</title><items><rdf:Seq>{li}</rdf:Seq></items></channel>
  {entries}
</rdf:RDF>"""


def _article(rows: list[list[str]]) -> str:
    """記事 HTML を組み立て。rows = [[済, 都道府県, 店舗名, 応募期間, 抽選形式, 当選発表日, 備考], ...]。"""
    trs = "".join(
        "<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows
    )
    return f"""<html><body><table id="myTable">
<thead><tr><th>済</th><th>都道府県</th><th>店舗名</th><th>応募期間</th><th>抽選形式</th><th>当選発表日</th><th>備考</th></tr></thead>
<tbody>{trs}</tbody></table></body></html>"""


def _make_fetcher(mapping: dict[str, str]):
    async def _fetch(url: str) -> str:
        return mapping.get(url, "")
    return _fetch


# ===== 基本 parsing =====


def test_extract_product_name_from_quoted():
    assert _extract_product_name_from_title(
        '拡張パック「アビスアイ」全国予約店舗まとめ'
    ) == "アビスアイ"


def test_extract_product_name_double_quote():
    assert _extract_product_name_from_title(
        "ポケモンカード『メガブレイブ』予約情報"
    ) == "メガブレイブ"


def test_extract_product_name_fallback():
    """「」が無い場合は全国より前を取る (簡易フォールバック)。"""
    assert _extract_product_name_from_title("ポケモンカード全国まとめ") == "ポケモンカード"


def test_normalize_retailer_known_patterns():
    assert _normalize_retailer("Amazon 招待販売") == "amazon"
    assert _normalize_retailer("楽天ブックス") == "rakuten_books"
    assert _normalize_retailer("TSUTAYA佐倉") == "tsutaya"
    assert _normalize_retailer("あみあみ") == "amiami"
    assert _normalize_retailer("セブンネット") == "seven_net"
    assert _normalize_retailer("ポケモンセンターメガトウキョー") == "pokemoncenter"


def test_normalize_retailer_unknown_returns_unknown():
    """パターン未登録の retailer は unknown を返す。"""
    assert _normalize_retailer("謎の TCG 店-XYZ") == "unknown"
    assert _normalize_retailer("") == "unknown"


def test_infer_sales_type_patterns():
    assert _infer_sales_type("抽選販売") == "lottery"
    assert _infer_sales_type("WEB抽選") == "lottery"
    assert _infer_sales_type("店頭抽選") == "lottery"
    assert _infer_sales_type("予約抽選") == "preorder_lottery"
    assert _infer_sales_type("招待リクエスト") == "invitation"
    assert _infer_sales_type("整理券配布") == "numbered_ticket"
    assert _infer_sales_type("先着販売") == "first_come"
    assert _infer_sales_type("") == "unknown"
    assert _infer_sales_type("不明形式") == "unknown"


def test_infer_sales_type_title_promotes_lottery_to_preorder():
    """記事タイトルに「予約」あり + カラムが抽選販売系 → preorder_lottery に昇格。
    content_dedupe_key の統合性向上 (c_labo_blog 由来の preorder_lottery と揃う)。
    """
    # カラム「抽選販売」単体なら lottery
    assert _infer_sales_type("抽選販売") == "lottery"
    # タイトルに「予約」あれば preorder_lottery に昇格
    assert _infer_sales_type("抽選販売", article_title="拡張パック「アビスアイ」予約まとめ") == "preorder_lottery"
    # WEB抽選 / 店頭抽選 も同様に昇格
    assert _infer_sales_type("WEB抽選", article_title="○○予約情報") == "preorder_lottery"
    assert _infer_sales_type("店頭抽選", article_title="商品予約開始のお知らせ") == "preorder_lottery"


def test_infer_sales_type_non_lottery_not_promoted():
    """先着・整理券・招待は「予約」タイトルでも昇格しない (sales_type の意味が異なる)。"""
    assert _infer_sales_type("先着販売", article_title="予約開始") == "first_come"
    assert _infer_sales_type("整理券配布", article_title="予約情報") == "numbered_ticket"
    assert _infer_sales_type("招待リクエスト", article_title="予約") == "invitation"


def test_normalize_retailer_new_patterns():
    """2026-04-24 追加パターン (TCG 専門店チェーン)。"""
    assert _normalize_retailer("BIGMAGIC 池袋") == "bigmagic"
    assert _normalize_retailer("magi大宮") == "magi"
    assert _normalize_retailer("WonderGOO瑞江") == "wondergoo"
    assert _normalize_retailer("カードボックス横浜西口") == "card_box"
    assert _normalize_retailer("カードキングダム秋葉原") == "card_kingdom"
    assert _normalize_retailer("イエローサブマリン") == "yellow_submarine"
    assert _normalize_retailer("チェルモ3rd") == "chelmo"
    assert _normalize_retailer("コレイズ") == "koreizu"
    assert _normalize_retailer("でじたみんYahoo!") == "dejitamin"


def test_parse_apply_end_basic():
    now = datetime(2026, 4, 22, 12, 0)
    dt = _parse_apply_end("4月22日(水)13:59まで", now=now)
    assert dt is not None
    assert dt.month == 4 and dt.day == 22


def test_parse_apply_end_year_correction():
    """年をまたいだ古い日付は翌年扱い (4 月に "12月〜" なら翌年 12 月)。"""
    # now=4/22, 入力 "12月1日" は 4 月基準で「過去」→ 翌年 12 月に繰り上げ
    now = datetime(2026, 4, 22)
    dt = _parse_apply_end("12月1日", now=now)
    # 実装上、 now より 30 日以上過去なら翌年扱い。12/1 は前年 12/1 相当で 4 ヶ月過去 → 翌年に繰り上がる
    assert dt is not None


def test_parse_apply_end_empty_returns_none():
    now = datetime(2026, 4, 22)
    assert _parse_apply_end("", now=now) is None
    assert _parse_apply_end("   ", now=now) is None


# ===== adapter 動作 =====


@pytest.mark.asyncio
async def test_pokemon_lottery_article_creates_candidates():
    """ポケカ + 抽選 の記事で、都道府県 allowlist 内の行が candidate 化される。"""
    url = "https://rare-zaiko.blog.jp/archives/30753655.html"
    xml = _rss([("拡張パック「アビスアイ」全国予約店舗まとめ", url)])
    article = _article([
        ["", "オンライン", "Amazon 招待販売", "4月22日(水)13:59まで", "抽選販売", "4月23日(木)", "メール購読"],
        ["", "東京都", "カードラボ秋葉原", "4月26日(土)00:00まで", "店頭抽選", "4月27日(日)", ""],
        # 東京近郊外 → skip
        ["", "大阪府", "TSUTAYA大阪", "4月26日まで", "店頭抽選", "4月27日", ""],
    ])
    adapter = RareZaikoAggregatorAdapter(
        xml=xml, article_fetcher=_make_fetcher({url: article}),
    )
    candidates = await adapter.run()
    assert len(candidates) == 2
    regions = {c.extracted_payload["region"] for c in candidates}
    assert regions == {"オンライン", "東京都"}
    amazon = next(c for c in candidates if "Amazon" in c.store_name)
    assert amazon.retailer_name == "amazon"
    # 記事タイトルに「予約」があるため、「抽選販売」カラム → preorder_lottery に昇格
    # (c_labo_blog 由来の preorder_lottery と同じ sales_type になり content_dedupe_key が揃う)
    assert amazon.sales_type == "preorder_lottery"
    assert amazon.apply_end_at is not None
    assert amazon.product_name_normalized == "アビスアイ"


@pytest.mark.asyncio
async def test_non_pokemon_article_is_skipped():
    """ポケモン関連キーワードがない記事は fetch しない。"""
    xml = _rss([("予約開始！スプラトゥーン レイダース", "https://rare-zaiko.blog.jp/x.html")])
    called = []

    async def _fetch(url: str) -> str:
        called.append(url)
        return _article([])

    adapter = RareZaikoAggregatorAdapter(xml=xml, article_fetcher=_fetch)
    candidates = await adapter.run()
    assert candidates == []
    assert called == []


@pytest.mark.asyncio
async def test_unknown_sales_type_row_is_skipped():
    """抽選形式が判別不能な行は candidate 発行しない (ノイズ排除)。"""
    url = "https://rare-zaiko.blog.jp/archives/x.html"
    xml = _rss([("拡張パック「アビスアイ」全国予約店舗まとめ", url)])
    article = _article([
        ["", "オンライン", "不明サイト", "", "", "", ""],
    ])
    adapter = RareZaikoAggregatorAdapter(
        xml=xml, article_fetcher=_make_fetcher({url: article}),
    )
    candidates = await adapter.run()
    assert candidates == []


@pytest.mark.asyncio
async def test_non_tokyo_metro_rows_are_skipped():
    """東京 1 都 3 県 / オンライン / 全国以外は skip。"""
    url = "https://rare-zaiko.blog.jp/archives/x.html"
    xml = _rss([("拡張パック「アビスアイ」全国予約店舗まとめ", url)])
    article = _article([
        ["", "北海道", "店舗A", "4月26日まで", "抽選販売", "", ""],
        ["", "沖縄県", "店舗B", "4月26日まで", "抽選販売", "", ""],
        ["", "埼玉県", "店舗C", "4月26日まで", "抽選販売", "", ""],
    ])
    adapter = RareZaikoAggregatorAdapter(
        xml=xml, article_fetcher=_make_fetcher({url: article}),
    )
    candidates = await adapter.run()
    # 埼玉県 (東京近郊) のみ通る
    assert len(candidates) == 1
    assert candidates[0].extracted_payload["region"] == "埼玉県"


@pytest.mark.asyncio
async def test_max_articles_caps_fetch():
    """max_articles で fetch 数を制限できる (レート抑制)。"""
    urls = [f"https://rare-zaiko.blog.jp/archives/{i}.html" for i in range(5)]
    xml = _rss([(f"拡張パック「商品{i}」まとめ", u) for i, u in enumerate(urls)])
    article = _article([
        ["", "オンライン", "Amazon 招待販売", "4月22日13:59まで", "抽選販売", "", ""],
    ])
    fetched: list[str] = []

    async def _fetch(url: str) -> str:
        fetched.append(url)
        return article

    adapter = RareZaikoAggregatorAdapter(xml=xml, article_fetcher=_fetch, max_articles=2)
    candidates = await adapter.run()
    # max_articles=2 → 2 記事分のみ
    assert len(fetched) == 2
    # 各記事 1 行なので candidate 2
    assert len(candidates) == 2
