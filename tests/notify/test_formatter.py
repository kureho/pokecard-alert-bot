from datetime import datetime

from pokebot.models import Event, EventKind, Priority
from pokebot.notify.formatter import format_event


def _make(**kw):
    base = dict(
        source="yodobashi",
        kind=EventKind.LOTTERY_OPEN,
        product_name="テラスタルフェスex",
        product_raw="raw",
        normalized_key="k",
        url="https://ex.com",
        detected_at=datetime(2026, 4, 20, 12),
        priority=Priority.CRITICAL,
    )
    base.update(kw)
    return Event(**base)


def test_critical_lottery_has_fire_emoji():
    msg = format_event(_make())
    assert msg.startswith("🔥")
    assert "抽選" in msg
    assert "テラスタルフェスex" in msg
    assert "ヨドバシ" in msg
    assert "https://ex.com" in msg


def test_restock_shows_green_circle():
    msg = format_event(_make(kind=EventKind.RESTOCK, priority=Priority.NORMAL))
    assert msg.startswith("🟢")
