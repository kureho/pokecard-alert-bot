from pathlib import Path

import pytest
from pokebot.parsers.yodobashi import lottery_list


@pytest.mark.asyncio
async def test_lottery_list_extracts_box_items():
    html = Path("tests/fixtures/yodobashi_lottery.html").read_text(encoding="utf-8")
    items = await lottery_list(html)
    titles = [i.raw_title for i in items]
    assert any("BOX" in t or "ボックス" in t for t in titles)
    assert all(i.url.startswith("https://") for i in items)
    assert all(i.kind_hint == "lottery_open" for i in items)
