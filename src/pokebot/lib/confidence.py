from __future__ import annotations

from datetime import datetime

# 信頼度閾値
CONFIDENCE_HIGH = 90
CONFIDENCE_MEDIUM = 70


def compute_confidence(
    *,
    source_trust_score: int,
    has_product_match: bool,
    has_apply_start: bool,
    has_apply_end: bool,
    has_result_at: bool,
    has_retailer: bool,
    has_store: bool,
    has_url: bool,
    sales_type_known: bool,
    product_name_ambiguous: bool = False,
    date_missing: bool = False,
    conflicting_existing: bool = False,
) -> int:
    """Phase 1 のシンプルなスコア計算。base = trust_score、検出要素で加点/減点。

    加点は 100 を上限としてキャップ→その後に減点を適用→ [0, 100] に最終クランプ。
    これにより「trust_score=100 の公式ソースはボーナスで膨らまず、ペナルティのみ反映される」
    という直感に沿った挙動になる。
    """
    score = source_trust_score
    if has_product_match:
        score += 5
    if has_apply_start:
        score += 5
    if has_apply_end:
        score += 5
    if has_result_at:
        score += 3
    if has_retailer:
        score += 2
    if has_store:
        score += 2
    if has_url:
        score += 2
    if sales_type_known:
        score += 5
    # cap bonuses first, then apply penalties
    score = min(100, score)
    if product_name_ambiguous:
        score -= 10
    if date_missing:
        score -= 10
    if conflicting_existing:
        score -= 15
    return max(0, min(100, score))


def classify_confirmation(
    *, confidence_score: int, source_trust_score: int
) -> str:
    """公式ソース (trust>=90) + 高信頼度 → confirmed、それ以外は unconfirmed。"""
    if source_trust_score >= 90 and confidence_score >= CONFIDENCE_HIGH:
        return "confirmed"
    if confidence_score >= CONFIDENCE_MEDIUM:
        return "unconfirmed"
    return "unconfirmed"
