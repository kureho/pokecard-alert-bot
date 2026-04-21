from __future__ import annotations

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
    # 追加: 本文抽出/タイトルのみの由来
    body_extracted: bool = False,
    title_only: bool = True,
) -> int:
    """trust 基礎 → body ボーナス → 情報ボーナス → ペナルティ → clamp。"""
    score = source_trust_score
    if body_extracted:
        score += 5
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
    else:
        # sales_type が unknown = 抽選か先着か不明。大幅減点。
        score -= 25
    if title_only and not body_extracted:
        # 本文未 fetch → 情報源がタイトルだけ → 信頼性大幅低下
        score -= 20
    if product_name_ambiguous:
        score -= 10
    if date_missing:
        score -= 15
    if conflicting_existing:
        score -= 15
    return max(0, min(100, score))


def classify_confirmation(
    *, confidence_score: int, source_trust_score: int
) -> str:
    """公式 (trust>=90) + 高信頼 → confirmed、それ以外は unconfirmed。"""
    if source_trust_score >= 90 and confidence_score >= CONFIDENCE_HIGH:
        return "confirmed"
    if confidence_score >= CONFIDENCE_MEDIUM:
        return "unconfirmed"
    return "unconfirmed"
