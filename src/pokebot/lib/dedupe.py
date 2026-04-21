from __future__ import annotations

from datetime import datetime


def _fmt(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%dT%H:%M") if value else "-"


def build_lottery_dedupe_key(
    *,
    normalized_product: str,
    normalized_retailer: str,
    normalized_store: str | None,
    sales_type: str,
    apply_start_at: datetime | None,
    apply_end_at: datetime | None,
) -> str:
    """ロッテリーイベントの dedupe キー。NULL は '-' で埋める。"""
    return "|".join([
        normalized_product or "-",
        normalized_retailer or "-",
        normalized_store or "-",
        sales_type or "-",
        _fmt(apply_start_at),
        _fmt(apply_end_at),
    ])


def build_notification_dedupe_key(
    *,
    lottery_dedupe_key: str,
    notification_type: str,
    content_version: str = "v1",
) -> str:
    """通知 dedupe キー: type が new なら送信は1回まで。update なら content_version で差別化。"""
    return f"{lottery_dedupe_key}#{notification_type}#{content_version}"
