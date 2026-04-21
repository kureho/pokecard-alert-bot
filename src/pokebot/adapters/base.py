from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Candidate:
    """adapter が抽出した1件の生候補。service 層で正規化して lottery_event へ変換される。

    sales_type: lottery / preorder_lottery / invitation / first_come / numbered_ticket / unknown
    """
    # 商品側
    product_name_raw: str
    product_name_normalized: str

    # 発生側
    retailer_name: str
    store_name: str | None = None
    sales_type: str = "unknown"

    # 時刻
    apply_start_at: datetime | None = None
    apply_end_at: datetime | None = None
    result_at: datetime | None = None
    purchase_start_at: datetime | None = None
    purchase_end_at: datetime | None = None

    # テキスト補足
    canonical_title: str = ""
    purchase_limit_text: str | None = None
    conditions_text: str | None = None

    # ソース情報
    source_name: str = ""
    source_url: str = ""
    source_title: str | None = None
    source_published_at: datetime | None = None
    raw_snapshot: str = ""

    # 追加情報
    extracted_payload: dict[str, Any] = field(default_factory=dict)

    # evidence 層 (Dispatch1): adapter は evidence_type を emit するだけ。
    # 数値化は service/confidence.py の evaluate_evidence() が行う。
    #   evidence_type: entry_page / product_page / official_notice / store_notice
    #     / faq_or_guide / search_result / rss_item / social_post / unknown
    #   entry_method: web_form / lottery_page / invite_request / secret_sale
    #     / in_store_ticket / app_only / unknown
    #   sale_status_hint: upcoming / accepting / result_waiting
    #     / purchase_window / ended / sold_out / unknown
    evidence_type: str = "unknown"
    application_url: str | None = None
    product_url: str | None = None
    entry_method: str = "unknown"
    sale_status_hint: str = "unknown"
    canonical_fields: dict[str, Any] = field(default_factory=dict)
    raw_text_excerpt: str = ""
    retailer_event_id: str | None = None
    selector_version: str = ""


class SourceAdapter(ABC):
    """1つのソースから Candidate のリストを生成する adapter。

    サブクラスは source_name を明示して fetch/parse を実装する。
    """

    #: sources テーブルの source_name と一致
    source_name: str = ""

    @abstractmethod
    async def run(self) -> list[Candidate]:
        """fetch + parse + candidate 構築を一気通貫で実行。失敗時は例外を投げる。"""
        raise NotImplementedError
