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
    """ロッテリーイベントの dedupe キー (legacy, retailer 込み)。

    UNIQUE 制約がある既存カラム lottery_events.dedupe_key 向け。
    新しい検知は content_dedupe_key を優先するが、互換性のため残す。
    """
    return "|".join([
        normalized_product or "-",
        normalized_retailer or "-",
        normalized_store or "-",
        sales_type or "-",
        _fmt(apply_start_at),
        _fmt(apply_end_at),
    ])


def build_content_dedupe_key(
    *,
    normalized_product: str,
    sales_type: str,
    apply_start_at: datetime | None,
    apply_end_at: datetime | None,
) -> str:
    """Content dedupe key (retailer 非依存)。

    同一商品・同一 sales_type・同一応募期間なら、retailer / store が違っても
    同じ event に統合する。product_name_normalized が空の場合は "-" で埋める
    が、その場合は衝突が多く発生するので upsert 側で追加判定する。
    """
    return "|".join([
        normalized_product or "-",
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
