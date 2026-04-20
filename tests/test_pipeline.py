from datetime import datetime

from pokebot.monitors import RawItem
from pokebot.pipeline import to_event
from pokebot.models import EventKind, Priority


def test_lottery_open_wins_over_restock():
    item = RawItem(
        source="yodobashi",
        raw_title="【抽選】【再販】拡張パック テラスタルフェスex BOX",
        url="https://x",
        kind_hint="restock",
    )
    ev = to_event(item, now=datetime(2026, 4, 20))
    assert ev.kind == EventKind.LOTTERY_OPEN


def test_box_lottery_gets_critical_priority():
    item = RawItem(source="yodobashi",
                   raw_title="【抽選】拡張パック テラスタルフェスex BOX",
                   url="https://x", kind_hint="lottery_open")
    ev = to_event(item, now=datetime(2026, 4, 20))
    assert ev.priority == Priority.CRITICAL


def test_non_box_announcement_gets_info_priority():
    item = RawItem(source="news",
                   raw_title="新弾発表",
                   url="https://x", kind_hint="announcement")
    ev = to_event(item, now=datetime(2026, 4, 20))
    assert ev.priority == Priority.INFO


def test_nameless_item_returns_none():
    item = RawItem(source="x", raw_title="   ", url="https://x", kind_hint="announcement")
    assert to_event(item, now=datetime(2026, 4, 20)) is None
