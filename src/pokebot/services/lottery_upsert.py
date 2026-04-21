from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from ..adapters.base import Candidate
from ..lib.confidence import classify_confirmation, compute_confidence
from ..lib.dedupe import build_lottery_dedupe_key
from ..lib.normalize import normalize_retailer, normalize_store
from ..storage.repos import LotteryEventRepo, ProductRepo, SourceRepo

log = logging.getLogger(__name__)

# 告知の source_published_at がこの窓より古い candidate は 'archived' 扱いで保存し、
# 通知対象から除外する。過去数ヶ月分の RSS 履歴が LINE に流れる事故を防ぐ。
SOURCE_FRESHNESS_WINDOW = timedelta(days=14)


@dataclass
class UpsertOutcome:
    event_id: int
    is_new: bool
    is_updated: bool
    dedupe_key: str


class LotteryEventUpsertService:
    """Candidate を lottery_events へ upsert。dedupe_key / diff / confidence を一括で扱う。"""

    # 差分通知の対象になる "意味差分" フィールド
    SIGNIFICANT_FIELDS = {
        "apply_start_at",
        "apply_end_at",
        "result_at",
        "purchase_start_at",
        "purchase_end_at",
        "sales_type",
        "status",
        "purchase_limit_text",
        "conditions_text",
    }

    def __init__(
        self,
        *,
        lottery_repo: LotteryEventRepo,
        product_repo: ProductRepo,
        source_repo: SourceRepo,
    ) -> None:
        self._lottery_repo = lottery_repo
        self._product_repo = product_repo
        self._source_repo = source_repo

    async def apply(self, candidate: Candidate, *, now: datetime) -> UpsertOutcome | None:
        """hint を含めた product_master 用候補や、必要情報欠落の候補は None。"""
        payload = candidate.extracted_payload or {}
        if payload.get("is_product_master_hint"):
            return None
        if not candidate.retailer_name or not candidate.canonical_title:
            return None

        normalized_retailer = normalize_retailer(candidate.retailer_name)
        normalized_store = normalize_store(candidate.store_name)

        product_id: int | None = None
        product_match = False
        if candidate.product_name_normalized:
            p = await self._product_repo.find_by_normalized(candidate.product_name_normalized)
            if p:
                product_id = p.id
                product_match = True

        dedupe_key = build_lottery_dedupe_key(
            normalized_product=candidate.product_name_normalized or "-",
            normalized_retailer=normalized_retailer,
            normalized_store=normalized_store,
            sales_type=candidate.sales_type or "unknown",
            apply_start_at=candidate.apply_start_at,
            apply_end_at=candidate.apply_end_at,
        )

        source = await self._source_repo.get_by_name(candidate.source_name)
        source_trust = source.trust_score if source else 50
        source_id = source.id if source else None

        body_extracted = bool((candidate.extracted_payload or {}).get("body_fetched"))
        title_only = not body_extracted

        # クロスソース corroboration: 同一 product が他ソースで検出されているか。
        # existing がある場合は existing 自身をカウント対象から除外する
        # (自分の別 snapshot を count に入れないため)。
        existing = await self._lottery_repo.find_by_dedupe_key(dedupe_key)
        cross_source_count = await self._lottery_repo.count_distinct_sources_for_product(
            candidate.product_name_normalized,
            exclude_event_id=existing.id if existing else None,
        )

        confidence = compute_confidence(
            source_trust_score=source_trust,
            has_product_match=product_match,
            has_apply_start=candidate.apply_start_at is not None,
            has_apply_end=candidate.apply_end_at is not None,
            has_result_at=candidate.result_at is not None,
            has_retailer=bool(candidate.retailer_name),
            has_store=bool(candidate.store_name),
            has_url=bool(candidate.source_url),
            sales_type_known=candidate.sales_type not in ("unknown", "", None),
            product_name_ambiguous=(
                not candidate.product_name_normalized
                or len(candidate.product_name_normalized) < 3
            ),
            date_missing=(
                candidate.apply_start_at is None and candidate.apply_end_at is None
            ),
            body_extracted=body_extracted,
            title_only=title_only,
            cross_source_count=cross_source_count,
        )
        status = classify_confirmation(
            confidence_score=confidence, source_trust_score=source_trust
        )

        # 告知の source_published_at が古すぎる場合は 'archived' 扱い。
        # 通知対象 (status='active') から自動的に外す。
        event_status = "active"
        if candidate.source_published_at is not None:
            age = now - candidate.source_published_at
            if age > SOURCE_FRESHNESS_WINDOW:
                event_status = "archived"

        # sales_type=unknown は抽選/先着の判別ができていない → 通知対象外
        if candidate.sales_type in ("unknown", "", None):
            event_status = "pending_review"

        if existing is None:
            new_id = await self._lottery_repo.create(
                product_id=product_id,
                retailer_name=candidate.retailer_name,
                store_name=candidate.store_name,
                canonical_title=candidate.canonical_title,
                sales_type=candidate.sales_type or "unknown",
                apply_start_at=candidate.apply_start_at,
                apply_end_at=candidate.apply_end_at,
                result_at=candidate.result_at,
                purchase_start_at=candidate.purchase_start_at,
                purchase_end_at=candidate.purchase_end_at,
                purchase_limit_text=candidate.purchase_limit_text,
                conditions_text=candidate.conditions_text,
                source_primary_url=candidate.source_url,
                official_confirmation_status=status,
                confidence_score=confidence,
                dedupe_key=dedupe_key,
                status=event_status,
                product_name_normalized=candidate.product_name_normalized,
            )
            if source_id:
                await self._lottery_repo.add_source_link(
                    new_id, source_id,
                    source_url=candidate.source_url,
                    source_title=candidate.source_title,
                    source_published_at=candidate.source_published_at,
                    raw_snapshot_hash=candidate.raw_snapshot,
                    extracted_payload=candidate.extracted_payload,
                )
            return UpsertOutcome(event_id=new_id, is_new=True, is_updated=False, dedupe_key=dedupe_key)

        # 既存: 差分比較
        updates: dict = {}
        for f in self.SIGNIFICANT_FIELDS:
            new_v = getattr(candidate, f, None)
            old_v = getattr(existing, f, None)
            # 下位レベル: None を上書きしない（情報が減る方向には動かさない）
            if new_v is not None and new_v != old_v:
                updates[f] = new_v

        # confidence / confirmation / product_id は毎回最新化
        updates["confidence_score"] = max(existing.confidence_score, confidence)
        updates["official_confirmation_status"] = status
        if product_id and existing.product_id != product_id:
            updates["product_id"] = product_id
        if candidate.source_url and existing.source_primary_url != candidate.source_url:
            updates["source_primary_url"] = candidate.source_url
        # 既存 event に product_name_normalized が未記録なら backfill
        if (
            candidate.product_name_normalized
            and not existing.product_name_normalized
        ):
            updates["product_name_normalized"] = candidate.product_name_normalized
        # 古い告知は retroactive に archive
        if event_status == "archived" and existing.status == "active":
            updates["status"] = "archived"

        meaningful_changes = any(k in self.SIGNIFICANT_FIELDS for k in updates.keys())

        if updates:
            await self._lottery_repo.update(existing.id, **updates)
        else:
            await self._lottery_repo.touch_last_seen(existing.id, now)

        if source_id:
            await self._lottery_repo.add_source_link(
                existing.id, source_id,
                source_url=candidate.source_url,
                source_title=candidate.source_title,
                source_published_at=candidate.source_published_at,
                raw_snapshot_hash=candidate.raw_snapshot,
                extracted_payload=candidate.extracted_payload,
            )

        return UpsertOutcome(
            event_id=existing.id,
            is_new=False,
            is_updated=meaningful_changes,
            dedupe_key=dedupe_key,
        )
