"""ドメインモデル定義。

MVP Phase 1 で扱うイベントは以下の kind を持つ:

- lottery_open: 抽選応募開始
- lottery_close: 抽選応募締切 (直前アラート)
- restock: 再販・在庫復活
- sale_resume: 販売再開

id は `(source, kind, normalized_key, 粒度化した日時)` から決定的に生成する。
同じ商品・同じイベントが短時間に複数回検出されても同じ id となるため、
INSERT ... ON CONFLICT DO NOTHING で自然に重複排除できる。
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from enum import IntEnum, StrEnum
from typing import Any

from pydantic import BaseModel, Field, computed_field


class EventKind(StrEnum):
    LOTTERY_OPEN = "lottery_open"
    LOTTERY_CLOSE = "lottery_close"
    RESTOCK = "restock"
    SALE_RESUME = "sale_resume"


class Priority(IntEnum):
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


def _bucket_datetime(dt: datetime, kind: EventKind) -> str:
    """イベント種別に応じて日時を粒度化し決定的 id のソースに使う。

    - lottery_open / sale_resume / restock は日単位 (同日中の揺れを吸収)
    - lottery_close は時間単位 (直前アラートは時間精度が要る)
    """
    if kind == EventKind.LOTTERY_CLOSE:
        return dt.strftime("%Y-%m-%dT%H")
    return dt.strftime("%Y-%m-%d")


def compute_event_id(
    source: str,
    kind: EventKind,
    normalized_key: str,
    bucket_dt: datetime,
) -> str:
    """決定的 id を生成する。

    同じ (source, kind, normalized_key, bucket) から常に同じ id が返る。
    """
    raw = f"{source}|{kind.value}|{normalized_key}|{_bucket_datetime(bucket_dt, kind)}"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    return digest[:16]


class Event(BaseModel):
    """検出された 1 イベント。

    - product_raw: 取得元での生の表示名 (ログ・デバッグ用)
    - product_name: 表示用に軽く整えた名前
    - normalized_key: 正規化キー (抽選開始→締切→再販 の突合に使う)
    - detected_at: 監視側で検出した時刻 (naive JST 想定)
    - source_ts: 元ソースでの公開/更新時刻 (取れないソースもあるので Optional)
    - lottery_deadline: 抽選応募の締切 (抽選系のみ)
    - extra: ソース固有の追加情報 (JSON シリアライズ可能な dict)
    """

    source: str
    kind: EventKind
    product_name: str
    product_raw: str
    normalized_key: str
    url: str
    detected_at: datetime
    source_ts: datetime | None = None
    price_yen: int | None = None
    lottery_deadline: datetime | None = None
    priority: Priority = Priority.NORMAL
    extra: dict[str, Any] = Field(default_factory=dict)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def id(self) -> str:
        bucket = self.source_ts or self.detected_at
        return compute_event_id(self.source, self.kind, self.normalized_key, bucket)
