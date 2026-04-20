from datetime import datetime

import pytest

from pokebot.models import Event, EventKind, Priority, compute_event_id


def _base_kwargs(**overrides):
    base = dict(
        source="yodobashi",
        kind=EventKind.LOTTERY_OPEN,
        product_name="テラスタルフェスex BOX",
        product_raw="【抽選】テラスタルフェスex BOX",
        normalized_key="拡張パック|テラスタルフェスex|2026-03-14|BOX",
        url="https://www.yodobashi.com/x",
        detected_at=datetime(2026, 4, 20, 12, 0, 0),
    )
    base.update(overrides)
    return base


def test_event_id_is_deterministic():
    a = Event(**_base_kwargs())
    b = Event(**_base_kwargs())
    assert a.id == b.id


def test_event_id_differs_when_kind_changes():
    a = Event(**_base_kwargs(kind=EventKind.LOTTERY_OPEN))
    b = Event(**_base_kwargs(kind=EventKind.LOTTERY_CLOSE))
    assert a.id != b.id


def test_event_id_differs_when_source_changes():
    a = Event(**_base_kwargs(source="yodobashi"))
    b = Event(**_base_kwargs(source="amazon"))
    assert a.id != b.id


def test_event_id_differs_when_normalized_key_changes():
    a = Event(**_base_kwargs())
    b = Event(**_base_kwargs(normalized_key="別商品|BOX"))
    assert a.id != b.id


def test_event_id_same_within_day_for_lottery_open():
    """lottery_open は日単位バケット。同じ日なら時刻が違っても同一 id。"""
    a = Event(**_base_kwargs(detected_at=datetime(2026, 4, 20, 9, 0, 0)))
    b = Event(**_base_kwargs(detected_at=datetime(2026, 4, 20, 23, 59, 0)))
    assert a.id == b.id


def test_event_id_differs_across_days_for_lottery_open():
    a = Event(**_base_kwargs(detected_at=datetime(2026, 4, 20, 12, 0, 0)))
    b = Event(**_base_kwargs(detected_at=datetime(2026, 4, 21, 12, 0, 0)))
    assert a.id != b.id


def test_event_id_uses_hour_bucket_for_lottery_close():
    a = Event(
        **_base_kwargs(
            kind=EventKind.LOTTERY_CLOSE,
            detected_at=datetime(2026, 4, 20, 12, 10, 0),
        )
    )
    b = Event(
        **_base_kwargs(
            kind=EventKind.LOTTERY_CLOSE,
            detected_at=datetime(2026, 4, 20, 12, 55, 0),
        )
    )
    c = Event(
        **_base_kwargs(
            kind=EventKind.LOTTERY_CLOSE,
            detected_at=datetime(2026, 4, 20, 13, 5, 0),
        )
    )
    assert a.id == b.id
    assert a.id != c.id


def test_event_id_prefers_source_ts_over_detected_at():
    a = Event(
        **_base_kwargs(
            detected_at=datetime(2026, 4, 20, 12, 0, 0),
            source_ts=datetime(2026, 4, 18, 0, 0, 0),
        )
    )
    b = Event(
        **_base_kwargs(
            detected_at=datetime(2026, 4, 21, 12, 0, 0),
            source_ts=datetime(2026, 4, 18, 23, 0, 0),
        )
    )
    assert a.id == b.id


def test_priority_default_is_normal():
    ev = Event(**_base_kwargs())
    assert ev.priority == Priority.NORMAL


def test_priority_critical_is_highest():
    assert int(Priority.CRITICAL) > int(Priority.HIGH)
    assert int(Priority.HIGH) > int(Priority.NORMAL)
    assert int(Priority.NORMAL) > int(Priority.LOW)


def test_extra_defaults_to_empty_dict():
    ev = Event(**_base_kwargs())
    assert ev.extra == {}


def test_compute_event_id_is_short_hash():
    eid = compute_event_id(
        "yodobashi", EventKind.RESTOCK, "key|BOX", datetime(2026, 4, 20, 12, 0)
    )
    assert isinstance(eid, str)
    assert len(eid) == 16


def test_event_model_rejects_unknown_kind():
    with pytest.raises(ValueError):
        Event(**_base_kwargs(kind="unknown_kind"))
