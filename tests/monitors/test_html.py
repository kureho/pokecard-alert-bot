from pathlib import Path

import pytest
from pokebot.monitors.html import HtmlMonitor
from pokebot.monitors.types import RawItem


async def _dummy_parser(html: str):
    assert "<html" in html.lower()
    return [
        RawItem(
            source="yodobashi",
            raw_title="【抽選】テラスタルフェスex BOX",
            url="https://www.yodobashi.com/product/1",
            kind_hint="lottery_open",
        )
    ]


@pytest.mark.asyncio
async def test_html_monitor_fetches_and_parses(httpx_mock):
    fixture = Path("tests/fixtures/yodobashi_lottery.html").read_text(encoding="utf-8")
    httpx_mock.add_response(url="https://www.yodobashi.com/lottery", text=fixture)
    m = HtmlMonitor(
        id_="yodobashi_lottery",
        url="https://www.yodobashi.com/lottery",
        interval_sec=120,
        parser=_dummy_parser,
    )
    items = list(await m.fetch())
    assert len(items) == 1
    assert items[0].kind_hint == "lottery_open"


@pytest.mark.asyncio
async def test_html_monitor_raises_on_5xx(httpx_mock):
    httpx_mock.add_response(url="https://example.invalid/x", status_code=503)
    m = HtmlMonitor(id_="x", url="https://example.invalid/x", interval_sec=60, parser=_dummy_parser)
    with pytest.raises(Exception):
        await m.fetch()
