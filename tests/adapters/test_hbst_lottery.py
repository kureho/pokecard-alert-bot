from pathlib import Path

import pytest

from pokebot.adapters.hbst_lottery import (
    HbstLotteryAdapter,
    _extract_application_url,
    _extract_product_name,
)


def test_extract_product_name_removes_date_prefix_and_quoted():
    title = (
        "【2026.04.17】※応募は終了しました抽選販売"
        "「ポケモンカードゲームMEGA ハイクラスパック メガドリームex（再販）」"
    )
    name = _extract_product_name(title)
    assert "メガドリーム" in name
    assert "応募は終了" not in name
    assert "2026" not in name


def test_extract_product_name_accepting_form():
    title = (
        "【2026.05.01】抽選販売「ポケモンカードゲームMEGA 拡張パック ニンジャスピナー」"
    )
    name = _extract_product_name(title)
    assert "ニンジャスピナー" in name


def test_extract_livepocket_url():
    body = "抽選受付ページリンク: https://livepocket.jp/e/78l3b お申し込みは..."
    assert _extract_application_url(body, "") == "https://livepocket.jp/e/78l3b"


def test_extract_livepocket_url_none_if_absent():
    assert _extract_application_url("no url here", "<html></html>") is None


@pytest.mark.asyncio
async def test_hbst_adapter_end_to_end_with_fixture():
    feed = Path("tests/fixtures/hbst_feed.xml").read_text(encoding="utf-8")
    article = Path("tests/fixtures/hbst_article.html").read_text(encoding="utf-8")

    async def fake_fetcher(url: str) -> str:
        return article

    adapter = HbstLotteryAdapter(xml=feed, body_fetcher=fake_fetcher)
    cands = await adapter.run()
    assert len(cands) >= 1
    first = cands[0]
    assert first.retailer_name == "hobby_station"
    assert first.evidence_type == "store_notice"
    assert first.sales_type == "lottery"
    # 全ての候補で normalize が効いているか
    for c in cands:
        assert c.product_name_normalized
        assert c.source_url.startswith("https://www.hbst.net/")


@pytest.mark.asyncio
async def test_hbst_adapter_skips_non_pokemon_entries():
    xml = """<?xml version="1.0"?>
    <rss><channel>
      <item>
        <title>【遊戯王】抽選販売</title>
        <link>https://www.hbst.net/?p=1</link>
      </item>
      <item>
        <title>ポケモンカードゲームの入荷情報</title>
        <link>https://www.hbst.net/?p=2</link>
      </item>
    </channel></rss>"""
    adapter = HbstLotteryAdapter(xml=xml)
    # 1件目: ポケモンキーワードなし → skip
    # 2件目: ポケモンキーワードあるが抽選/予約キーワードなし → skip
    cands = await adapter.run()
    assert cands == []


@pytest.mark.asyncio
async def test_hbst_adapter_applies_max_body_fetch():
    xml = """<?xml version="1.0"?>
    <rss><channel>
      <item><title>抽選販売「ポケモンカードゲームMEGA アビスアイ」</title><link>https://www.hbst.net/?p=1</link></item>
      <item><title>抽選販売「ポケモンカードゲームMEGA ニンジャスピナー」</title><link>https://www.hbst.net/?p=2</link></item>
      <item><title>抽選販売「ポケモンカードゲームMEGA メガブレイブ」</title><link>https://www.hbst.net/?p=3</link></item>
    </channel></rss>"""
    calls: list[str] = []

    async def fake_fetcher(url: str) -> str:
        calls.append(url)
        # body_info が何も抽出できない → skip される
        return "<html><body>empty</body></html>"

    adapter = HbstLotteryAdapter(xml=xml, body_fetcher=fake_fetcher, max_body_fetch=2)
    await adapter.run()
    assert len(calls) == 2
