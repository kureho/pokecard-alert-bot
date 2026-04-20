import pytest
from pokebot.monitors import Monitor, RawItem


class DummyMonitor(Monitor):
    id = "dummy"
    interval_sec = 60

    async def fetch(self):
        return [RawItem(source="dummy", raw_title="t", url="https://x", kind_hint="restock")]


@pytest.mark.asyncio
async def test_dummy_monitor_returns_items():
    m = DummyMonitor()
    items = list(await m.fetch())
    assert items[0].raw_title == "t"
