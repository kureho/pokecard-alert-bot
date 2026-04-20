from pathlib import Path

import pytest
from pokebot.monitors.feed import FeedMonitor
from pokebot.monitors.types import RawItem


async def _parser(feed):
    out = []
    for e in feed.entries[:3]:
        out.append(RawItem(
            source="pokeca_sokuhou",
            raw_title=e.title,
            url=e.link,
            kind_hint="announcement",
        ))
    return out


@pytest.mark.asyncio
async def test_feed_monitor_parses_entries(httpx_mock):
    xml = Path("tests/fixtures/pokeca_sokuhou.xml").read_text(encoding="utf-8")
    httpx_mock.add_response(url="https://example.invalid/feed", text=xml)
    m = FeedMonitor(
        id_="pokeca_sokuhou",
        url="https://example.invalid/feed",
        interval_sec=180,
        parser=_parser,
    )
    items = list(await m.fetch())
    assert len(items) == 3
