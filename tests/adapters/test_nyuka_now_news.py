from pathlib import Path

import pytest

from pokebot.adapters.nyuka_now_news import NyukaNowNewsAdapter


@pytest.mark.asyncio
async def test_nyuka_now_news_extracts_pokemon_with_retailer():
    xml = Path("tests/fixtures/nyuka_now_news_feed.xml").read_text(encoding="utf-8")
    adapter = NyukaNowNewsAdapter(xml=xml)
    candidates = await adapter.run()
    assert len(candidates) >= 1
    # アビスアイの Amazon 販売予定が検出される
    abyss = [
        c for c in candidates
        if "アビスアイ" in c.canonical_title and c.retailer_name == "amazon"
    ]
    assert abyss, (
        "expected abyss Amazon, got: "
        f"{[(c.retailer_name, c.canonical_title[:40]) for c in candidates[:5]]}"
    )
    c = abyss[0]
    # apply_start が title の「4月20日(月)14時」から抽出される
    assert c.apply_start_at is not None
    assert c.apply_start_at.month == 4 and c.apply_start_at.day == 20
    assert c.apply_start_at.hour == 14
