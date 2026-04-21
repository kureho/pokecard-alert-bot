from pathlib import Path

import pytest

from pokebot.adapters.pokecen_online_lottery import PokecenOnlineLotteryAdapter


@pytest.mark.asyncio
async def test_empty_state_returns_no_candidates():
    html = Path("tests/fixtures/pokecen_online_apply.html").read_text(encoding="utf-8")
    adapter = PokecenOnlineLotteryAdapter(html=html)
    candidates = await adapter.run()
    assert candidates == []
