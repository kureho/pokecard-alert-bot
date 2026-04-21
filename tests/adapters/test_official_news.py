from pathlib import Path

import pytest

from pokebot.adapters.official_news import PokemonOfficialNewsAdapter


@pytest.mark.asyncio
async def test_official_news_extracts_lottery_related_entries():
    html = Path("tests/fixtures/pokemon_official_news.html").read_text(encoding="utf-8")
    adapter = PokemonOfficialNewsAdapter(html=html)
    candidates = await adapter.run()
    assert len(candidates) >= 1
    # 全て 抽選/販売/再販/発売 系のタイトルを含むはず
    assert all(
        any(k in c.canonical_title for k in ("抽選", "先着", "整理券", "発売", "新弾", "リリース"))
        for c in candidates
    )


@pytest.mark.asyncio
async def test_official_news_adapter_name():
    assert PokemonOfficialNewsAdapter().source_name == "pokemon_official_news"
