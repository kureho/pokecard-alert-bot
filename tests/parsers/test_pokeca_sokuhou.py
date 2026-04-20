from pathlib import Path

import feedparser
import pytest
from pokebot.parsers.pokeca_sokuhou import feed as parse_feed


@pytest.mark.asyncio
async def test_feed_parses_entries():
    xml = Path("tests/fixtures/pokeca_sokuhou.xml").read_text(encoding="utf-8")
    parsed = feedparser.parse(xml)
    items = await parse_feed(parsed)
    assert len(items) >= 1
    assert all(i.source == "pokeca_sokuhou" for i in items)


@pytest.mark.asyncio
async def test_feed_classifies_kind_by_keyword():
    xml = Path("tests/fixtures/pokeca_sokuhou.xml").read_text(encoding="utf-8")
    parsed = feedparser.parse(xml)
    items = await parse_feed(parsed)
    lottery = [i for i in items if "抽選" in i.raw_title]
    restock = [i for i in items if any(k in i.raw_title for k in ("再販", "入荷"))]
    for i in lottery:
        assert i.kind_hint == "lottery_open"
    for i in restock:
        assert i.kind_hint == "restock"
