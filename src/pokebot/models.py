"""ドメインモデル定義。"""

from __future__ import annotations

import hashlib
from datetime import datetime
from enum import IntEnum, StrEnum

from pydantic import BaseModel, Field


class EventKind(StrEnum):
    LOTTERY_OPEN = "lottery_open"
    LOTTERY_CLOSE = "lottery_close"
    RESTOCK = "restock"
    ANNOUNCEMENT = "announcement"
    NEW_PRODUCT = "new_product"
    LOTTERY_RESULT = "lottery_result"


class Priority(IntEnum):
    CRITICAL = 0
    NORMAL = 1
    INFO = 2


class Event(BaseModel):
    source: str
    kind: EventKind
    product_name: str
    product_raw: str
    normalized_key: str
    url: str
    detected_at: datetime
    priority: Priority
    source_ts: datetime | None = None
    price_yen: int | None = None
    lottery_deadline: datetime | None = None
    extra: dict = Field(default_factory=dict)

    @property
    def id(self) -> str:
        key = f"{self.source}|{self.kind}|{self.normalized_key}".encode("utf-8")
        return hashlib.sha256(key).hexdigest()[:32]
