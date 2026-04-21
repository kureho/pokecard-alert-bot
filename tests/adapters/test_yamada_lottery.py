from pathlib import Path

import pytest

from pokebot.adapters.yamada_lottery import (
    YamadaLotteryAdapter,
    _INFO_URL_RE,
    _extract_product_name_from_title,
)


def test_info_url_regex_matches_yamada_pattern():
    top = '<a href="https://www.yamada-denki.jp/information/260420_pokemon-card/">'
    paths = [m.group(0) for m in _INFO_URL_RE.finditer(top)]
    assert len(paths) == 1
    assert "260420_pokemon-card" in paths[0]


def test_info_url_regex_ignores_unrelated():
    top = (
        '<a href="/information/260420_pokemon-card/">A</a>'
        '<a href="/information/other-info/">B</a>'
        '<a href="/service/cp_pokemon-goods/">C</a>'
    )
    matches = [m.group(0) for m in _INFO_URL_RE.finditer(top)]
    assert len(matches) == 1
    assert matches[0].startswith("/information/260420_pokemon-card")


def test_extract_product_name_from_quoted_title():
    title = (
        "「ポケモンカードゲーム MEGA 拡張パック アビスアイ」の抽選販売お申し込み受付 "
        "｜ヤマダデンキ YAMADA DENKI Co.,LTD."
    )
    name = _extract_product_name_from_title(title)
    assert "アビスアイ" in name
    assert "ヤマダ" not in name


def test_extract_product_name_fallback_on_no_quotes():
    title = "ポケモンカードゲーム 拡張パック の抽選販売お申し込み ｜ヤマダ"
    name = _extract_product_name_from_title(title)
    assert "ヤマダ" not in name
    assert "ポケモンカード" in name


@pytest.mark.asyncio
async def test_yamada_adapter_end_to_end_with_fixture():
    top_html = Path("tests/fixtures/yamada_top.html").read_text(encoding="utf-8")
    pokemon_html = Path("tests/fixtures/yamada_pokemon_card.html").read_text(
        encoding="utf-8"
    )

    async def fake_fetcher(url: str) -> str:
        assert "pokemon-card" in url
        return pokemon_html

    adapter = YamadaLotteryAdapter(top_html=top_html, body_fetcher=fake_fetcher)
    candidates = await adapter.run()
    assert len(candidates) == 1
    c = candidates[0]
    assert c.retailer_name == "yamada"
    assert c.sales_type == "lottery"
    assert c.evidence_type == "store_notice"
    assert c.entry_method == "app_only"
    assert "アビスアイ" in c.product_name_raw
    assert c.apply_start_at is not None
    assert c.apply_end_at is not None
    assert c.result_at is not None
    assert c.purchase_start_at is not None
    assert c.purchase_end_at is not None
    assert c.source_url.startswith("https://www.yamada-denki.jp/information/")
    assert c.application_url == c.source_url


@pytest.mark.asyncio
async def test_yamada_adapter_no_banner_returns_empty():
    top_html = "<html><body>ポケカバナーなし</body></html>"
    adapter = YamadaLotteryAdapter(top_html=top_html)
    candidates = await adapter.run()
    assert candidates == []


@pytest.mark.asyncio
async def test_yamada_adapter_body_fetch_capped():
    top_html = (
        '<a href="/information/260420_pokemon-card/">a</a>'
        '<a href="/information/260421_pokemon-card/">b</a>'
        '<a href="/information/260422_pokemon-card/">c</a>'
    )
    calls: list[str] = []

    async def fake_fetcher(url: str) -> str:
        calls.append(url)
        # 本文なし → adapter は skip する (has_any_date False)
        return "<html><body>no dates</body></html>"

    adapter = YamadaLotteryAdapter(
        top_html=top_html, body_fetcher=fake_fetcher, max_body_fetch=2
    )
    await adapter.run()
    assert len(calls) == 2
