from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from ..adapters.base import Candidate
from ..lib.confidence import (
    EvidenceFields,
    build_evidence_summary,
    evaluate_evidence,
    map_to_legacy_status,
)
from ..lib.dedupe import build_lottery_dedupe_key
from ..lib.normalize import normalize_retailer, normalize_store
from ..lib.snapshot import page_fingerprint
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


def _infer_sale_status(
    *,
    now: datetime,
    apply_start_at: datetime | None,
    apply_end_at: datetime | None,
    result_at: datetime | None,
    purchase_end_at: datetime | None,
    hint: str,
) -> str:
    """時刻軸ベースで sale_status を推定。判定不能なら hint を尊重、最後は 'unknown'。"""
    if apply_start_at and apply_end_at:
        if now < apply_start_at:
            return "upcoming"
        if now <= apply_end_at:
            return "accepting"
        if result_at and now <= result_at:
            return "result_waiting"
        if purchase_end_at and now <= purchase_end_at:
            return "purchase_window"
        return "ended"
    if hint and hint != "unknown":
        return hint
    return "unknown"


class LotteryEventUpsertService:
    """Candidate を lottery_events へ upsert。dedupe_key / diff / evidence 評価を一括で扱う。"""

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
        source_id = source.id if source else None

        title_only = not bool(payload.get("body_fetched"))

        # クロスソース corroboration: 同一 product が他ソースで検出されているか。
        existing = await self._lottery_repo.find_by_dedupe_key(dedupe_key)
        cross_source_count = await self._lottery_repo.count_distinct_sources_for_product(
            candidate.product_name_normalized,
            exclude_event_id=existing.id if existing else None,
        )

        # Dispatch1: evidence ベース評価。
        fields = EvidenceFields(
            has_apply_start=candidate.apply_start_at is not None,
            has_apply_end=candidate.apply_end_at is not None,
            has_result_at=candidate.result_at is not None,
            has_purchase_window=(
                candidate.purchase_start_at is not None
                or candidate.purchase_end_at is not None
            ),
            has_retailer=bool(candidate.retailer_name),
            has_store=bool(candidate.store_name),
            has_product_match=product_match,
            has_url=bool(
                candidate.source_url
                or candidate.application_url
                or candidate.product_url
            ),
            sales_type_known=candidate.sales_type not in ("unknown", "", None),
            cross_source_count=cross_source_count,
            title_only=title_only,
            product_name_ambiguous=(
                not candidate.product_name_normalized
                or len(candidate.product_name_normalized) < 3
            ),
            conflicting_existing=False,  # Phase 2 で実装
        )
        level, evidence_score = evaluate_evidence(
            evidence_type=candidate.evidence_type or "unknown",
            fields=fields,
        )
        legacy_status = map_to_legacy_status(level)
        evidence_summary = build_evidence_summary(
            evidence_type=candidate.evidence_type or "unknown",
            has_apply_period=fields.has_apply_start or fields.has_apply_end,
            has_result=fields.has_result_at,
            sales_type=candidate.sales_type or "unknown",
        )

        # 本文抜粋 (raw_text_excerpt) の候補: payload.text_preview > candidate.raw_text_excerpt
        body_text_for_fp = (
            payload.get("text_preview", "") or candidate.raw_text_excerpt or ""
        )
        page_fp = page_fingerprint(
            title=candidate.canonical_title or "",
            body_text=body_text_for_fp,
            apply_start_at=candidate.apply_start_at,
            apply_end_at=candidate.apply_end_at,
            result_at=candidate.result_at,
            retailer=normalized_retailer,
            product_name_normalized=candidate.product_name_normalized or "",
        )

        sale_status = _infer_sale_status(
            now=now,
            apply_start_at=candidate.apply_start_at,
            apply_end_at=candidate.apply_end_at,
            result_at=candidate.result_at,
            purchase_end_at=candidate.purchase_end_at,
            hint=candidate.sale_status_hint or "unknown",
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

        evidence_fields_for_link = dict(
            evidence_type=candidate.evidence_type or "unknown",
            evidence_strength=evidence_score,
            selector_version=candidate.selector_version or "",
            canonical_fields=candidate.canonical_fields or None,
            raw_text_excerpt=(candidate.raw_text_excerpt or "")[:2000],
        )

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
                official_confirmation_status=legacy_status,
                confidence_score=evidence_score,
                dedupe_key=dedupe_key,
                status=event_status,
                product_name_normalized=candidate.product_name_normalized,
                application_url=candidate.application_url,
                product_url=candidate.product_url,
                entry_method=candidate.entry_method or "unknown",
                sale_status=sale_status,
                page_fingerprint=page_fp,
                evidence_score=evidence_score,
                evidence_summary=evidence_summary,
                retailer_event_id=candidate.retailer_event_id,
                confidence_level=level.value,
            )
            if source_id:
                await self._lottery_repo.add_source_link(
                    new_id, source_id,
                    source_url=candidate.source_url,
                    source_title=candidate.source_title,
                    source_published_at=candidate.source_published_at,
                    raw_snapshot_hash=candidate.raw_snapshot,
                    extracted_payload=candidate.extracted_payload,
                    **evidence_fields_for_link,
                )
            return UpsertOutcome(event_id=new_id, is_new=True, is_updated=False, dedupe_key=dedupe_key)

        # 既存: 差分比較
        updates: dict = {}
        for f in self.SIGNIFICANT_FIELDS:
            new_v = getattr(candidate, f, None)
            old_v = getattr(existing, f, None)
            if new_v is not None and new_v != old_v:
                updates[f] = new_v

        # confidence 系は毎回最新化。evidence_score は新しい方が強ければ採用。
        new_conf_score = max(existing.confidence_score, evidence_score)
        updates["confidence_score"] = new_conf_score
        updates["official_confirmation_status"] = legacy_status
        # 既存の confidence_level を弱くする方向の上書きはしない。
        # NULL (既存 event) or 同等以下 → 新 level を採用。
        if existing.confidence_level is None or evidence_score >= (existing.evidence_score or 0):
            updates["confidence_level"] = level.value
            updates["evidence_score"] = evidence_score
            updates["evidence_summary"] = evidence_summary
        # 非破壊 enrichment: 既存 NULL 時のみ埋める。
        if existing.application_url is None and candidate.application_url:
            updates["application_url"] = candidate.application_url
        if existing.product_url is None and candidate.product_url:
            updates["product_url"] = candidate.product_url
        if (
            existing.entry_method in (None, "unknown", "")
            and candidate.entry_method
            and candidate.entry_method != "unknown"
        ):
            updates["entry_method"] = candidate.entry_method
        # sale_status は時刻軸由来なので常に最新化。
        if sale_status and sale_status != existing.sale_status:
            updates["sale_status"] = sale_status
        if existing.page_fingerprint is None:
            updates["page_fingerprint"] = page_fp
        if existing.retailer_event_id is None and candidate.retailer_event_id:
            updates["retailer_event_id"] = candidate.retailer_event_id

        if product_id and existing.product_id != product_id:
            updates["product_id"] = product_id
        if candidate.source_url and existing.source_primary_url != candidate.source_url:
            updates["source_primary_url"] = candidate.source_url
        if (
            candidate.product_name_normalized
            and not existing.product_name_normalized
        ):
            updates["product_name_normalized"] = candidate.product_name_normalized
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
                **evidence_fields_for_link,
            )

        return UpsertOutcome(
            event_id=existing.id,
            is_new=False,
            is_updated=meaningful_changes,
            dedupe_key=dedupe_key,
        )
