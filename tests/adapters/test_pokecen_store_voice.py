from pathlib import Path

import pytest

from pokebot.adapters.pokecen_store_voice import PokecenStoreVoiceAdapter
from pokebot.lib.title_classifier import TitleCategory


@pytest.mark.asyncio
async def test_extracts_lottery_entries_from_real_feed():
    xml = Path("tests/fixtures/stv_megatokyo_atom.xml").read_text(encoding="utf-8")

    async def _fake_fetcher(url):
        # body 情報なし → RELEASE_ANNOUNCE 系は skip されるが SALES_METHOD 等は unknown で残る
        return "<html><body><p>本文なし</p></body></html>"

    adapter = PokecenStoreVoiceAdapter(
        feeds={"megatokyo": xml}, body_fetcher=_fake_fetcher, max_body_fetch=50
    )
    candidates = await adapter.run()
    assert len(candidates) >= 1
    for c in candidates:
        assert c.retailer_name == "pokemoncenter"
        assert c.store_name and "メガトウキョー" in c.store_name
        assert c.source_name == "pokemoncenter_store_voice"
        # 過去イベ/大会系が除外されていることを確認
        cat = c.extracted_payload.get("title_category")
        assert cat not in (
            str(TitleCategory.IRRELEVANT),
            str(TitleCategory.LOTTERY_CLOSED),
            str(TitleCategory.LOTTERY_RESULT),
        )


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
