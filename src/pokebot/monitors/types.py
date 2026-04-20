from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class RawItem:
    source: str
    raw_title: str
    url: str
    kind_hint: str
    source_ts: datetime | None = None
    price_yen: int | None = None
    lottery_deadline: datetime | None = None
    extra: dict | None = None
