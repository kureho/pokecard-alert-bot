from __future__ import annotations

from datetime import datetime

from .models import Event, EventKind, Priority
from .monitors import RawItem
from .normalize import normalize_title

_KIND_PRIORITY = [
    EventKind.LOTTERY_OPEN,
    EventKind.RESTOCK,
    EventKind.NEW_PRODUCT,
    EventKind.ANNOUNCEMENT,
    EventKind.LOTTERY_CLOSE,
    EventKind.LOTTERY_RESULT,
]

_TITLE_TO_KIND = [
    ("抽選", EventKind.LOTTERY_OPEN),
    ("再販", EventKind.RESTOCK),
    ("入荷", EventKind.RESTOCK),
    ("発売", EventKind.NEW_PRODUCT),
]


def _choose_kind(raw_title: str, hint: str) -> EventKind:
    from_title = None
    for kw, k in _TITLE_TO_KIND:
        if kw in raw_title:
            from_title = k
            break
    from_hint = EventKind(hint) if hint in {e.value for e in EventKind} else EventKind.ANNOUNCEMENT
    candidates = [k for k in [from_title, from_hint] if k is not None]
    return min(candidates, key=_KIND_PRIORITY.index)


def _priority(kind: EventKind, is_box: bool) -> Priority:
    if is_box and kind in (EventKind.LOTTERY_OPEN, EventKind.RESTOCK):
        return Priority.CRITICAL
    if kind in (EventKind.NEW_PRODUCT, EventKind.LOTTERY_OPEN, EventKind.RESTOCK):
        return Priority.NORMAL
    return Priority.INFO


def to_event(item: RawItem, *, now: datetime) -> Event | None:
    n = normalize_title(item.raw_title)
    if not n.product_name:
        return None
    kind = _choose_kind(item.raw_title, item.kind_hint)
    return Event(
        source=item.source,
        kind=kind,
        product_name=n.product_name,
        product_raw=item.raw_title,
        normalized_key=n.key(url=item.url),
        url=item.url,
        detected_at=now,
        source_ts=item.source_ts,
        price_yen=item.price_yen,
        lottery_deadline=item.lottery_deadline,
        priority=_priority(kind, n.is_box),
        extra=item.extra or {},
    )
