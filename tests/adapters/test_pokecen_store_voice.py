from pathlib import Path

import pytest

from pokebot.adapters.pokecen_store_voice import PokecenStoreVoiceAdapter
from pokebot.lib.title_classifier import TitleCategory


@pytest.mark.asyncio
async def test_extracts_lottery_entries_from_real_feed():
    xml = Path("tests/fixtures/stv_megatokyo_atom.xml").read_text(encoding="utf-8")

    async def _fake_fetcher(url):
        # 実運用の「販売方法について」系記事を想定した本文。抽選キーワード入りで
        # sales_type=lottery として候補化される。
        return (
            "<html><body><p>抽選販売を実施します。"
            "応募期間: 4月20日 10:00 〜 4月25日 18:00</p></body></html>"
        )

    adapter = PokecenStoreVoiceAdapter(
        feeds={"megatokyo": xml}, body_fetcher=_fake_fetcher, max_body_fetch=50
    )
    candidates = await adapter.run()
    assert len(candidates) >= 1
    for c in candidates:
        assert c.retailer_name == "pokemoncenter"
        assert c.store_name and "メガトウキョー" in c.store_name
        assert c.source_name == "pokemoncenter_store_voice"
        # 新仕様: sales_type が unknown の candidate は発行されない
        assert c.sales_type != "unknown"
        # 過去イベ/大会系が除外されていることを確認
        cat = c.extracted_payload.get("title_category")
        assert cat not in (
            str(TitleCategory.IRRELEVANT),
            str(TitleCategory.LOTTERY_CLOSED),
            str(TitleCategory.LOTTERY_RESULT),
        )


@pytest.mark.asyncio
async def test_skips_non_tokyo_metro_shops():
    """東京近郊 (1都3県) 以外の shop_key は feed 取得せずスキップ。"""
    xml_fukuoka = (
        '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">'
        "<entry><title>【フクオカ】アビスアイ抽選販売のお知らせ</title>"
        '<link href="https://ex/fukuoka/1"/></entry></feed>'
    )
    fetched_urls: list[str] = []

    async def _fake_fetcher(url):
        fetched_urls.append(url)
        return "<html></html>"

    adapter = PokecenStoreVoiceAdapter(
        feeds={"megatokyo": None, "fukuoka": xml_fukuoka},  # megatokyo feed 未提供
        body_fetcher=_fake_fetcher,
    )
    candidates = await adapter.run()
    # fukuoka は除外されるので entry があっても candidate 0
    assert candidates == []
    # fukuoka の body fetch も発生しない (feed 自体スキップ)
    assert fetched_urls == []


@pytest.mark.asyncio
async def test_no_matching_keyword_returns_empty():
    xml = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><entry><title>無関係な告知</title><link href="https://ex/1"/></entry></feed>"""

    async def _fake_fetcher(url):
        return "<html></html>"

    adapter = PokecenStoreVoiceAdapter(
        feeds={"megatokyo": xml}, body_fetcher=_fake_fetcher
    )
    candidates = await adapter.run()
    assert candidates == []


@pytest.mark.asyncio
async def test_sales_method_title_with_body_lottery_keyword_creates_candidate():
    """title が「販売方法について」(SALES_METHOD) でも、body に「抽選」があれば sales_type=lottery で発行。"""
    xml = (
        '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">'
        "<entry><title>【ポケモンセンターメガトウキョー】5月22日発売商品の販売方法について</title>"
        '<link href="https://ex/stv/megatokyo/1"/></entry></feed>'
    )

    async def _fake_fetcher(url):
        return (
            "<html><body><h1>販売方法について</h1>"
            "<p>抽選販売を実施します。応募期間: 5月10日 10:00 〜 5月14日 23:59</p>"
            "</body></html>"
        )

    adapter = PokecenStoreVoiceAdapter(
        feeds={"megatokyo": xml}, body_fetcher=_fake_fetcher
    )
    candidates = await adapter.run()
    assert len(candidates) == 1
    c = candidates[0]
    assert c.sales_type == "lottery"
    assert c.apply_start_at is not None
    assert c.apply_end_at is not None


@pytest.mark.asyncio
async def test_sales_method_title_without_body_keyword_is_skipped():
    """title が SALES_METHOD で body にも判別キーワードがなければ candidate を発行しない (ノイズ排除)。"""
    xml = (
        '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">'
        "<entry><title>【ポケモンセンターメガトウキョー】3月13日発売のポケモンカードゲーム関連商品の販売方法について</title>"
        '<link href="https://ex/stv/megatokyo/2"/></entry></feed>'
    )

    async def _fake_fetcher(url):
        # 本文に抽選/先着/整理券/招待 いずれも含まない
        return "<html><body><h1>販売方法について</h1><p>発売日は3月13日です。</p></body></html>"

    adapter = PokecenStoreVoiceAdapter(
        feeds={"megatokyo": xml}, body_fetcher=_fake_fetcher
    )
    candidates = await adapter.run()
    assert candidates == [], "sales_type 判別不能な SALES_METHOD は candidate を発行しない"


@pytest.mark.asyncio
async def test_sales_method_title_with_body_first_come_keyword():
    """body に「先着」→ sales_type=first_come。"""
    xml = (
        '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">'
        "<entry><title>【ポケモンセンターメガトウキョー】新商品の販売方法について</title>"
        '<link href="https://ex/stv/megatokyo/3"/></entry></feed>'
    )

    async def _fake_fetcher(url):
        return "<html><body><h1>販売方法</h1><p>先着順で販売します。5月22日14:00から。</p></body></html>"

    adapter = PokecenStoreVoiceAdapter(
        feeds={"megatokyo": xml}, body_fetcher=_fake_fetcher
    )
    candidates = await adapter.run()
    assert len(candidates) == 1
    assert candidates[0].sales_type == "first_come"
