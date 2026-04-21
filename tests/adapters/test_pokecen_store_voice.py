from pathlib import Path

import pytest

from pokebot.adapters.pokecen_store_voice import PokecenStoreVoiceAdapter


@pytest.mark.asyncio
async def test_extracts_lottery_entries_from_real_feed():
    xml = Path("tests/fixtures/stv_megatokyo_atom.xml").read_text(encoding="utf-8")
    adapter = PokecenStoreVoiceAdapter(feeds={"megatokyo": xml})
    candidates = await adapter.run()
    # メガトウキョー feed には「3月13日（金）発売のポケモンカードゲーム関連商品の販売方法について」等が入っている想定
    assert len(candidates) >= 1
    for c in candidates:
        assert c.retailer_name == "pokemoncenter"
        assert c.store_name and "メガトウキョー" in c.store_name
        assert c.source_name == "pokemoncenter_store_voice"


@pytest.mark.asyncio
async def test_no_matching_keyword_returns_empty():
    xml = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><entry><title>無関係な告知</title><link href="https://ex/1"/></entry></feed>"""
    adapter = PokecenStoreVoiceAdapter(feeds={"megatokyo": xml})
    candidates = await adapter.run()
    assert candidates == []
