from datetime import datetime

from pokebot.models import Event, EventKind, Priority


def _common() -> dict:
    return dict(
        source="yodobashi",
        kind=EventKind.LOTTERY_OPEN,
        product_name="テラスタルフェスex BOX",
        product_raw="【抽選】テラスタルフェスex BOX",
        normalized_key="拡張パック|テラスタルフェスex|2026-03-14|BOX",
        url="https://www.yodobashi.com/x",
        detected_at=datetime(2026, 4, 20, 12, 0, 0),
        priority=Priority.CRITICAL,
    )


def test_event_id_is_deterministic():
    a = Event(**_common())
    b = Event(**_common())
    assert a.id == b.id


def test_event_id_differs_by_kind():
    base = dict(_common())
    base.pop("kind")
    a = Event(kind=EventKind.LOTTERY_OPEN, **base)
    b = Event(kind=EventKind.RESTOCK, **base)
    assert a.id != b.id
