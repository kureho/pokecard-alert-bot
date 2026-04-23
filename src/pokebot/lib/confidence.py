from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

# 信頼度閾値 (legacy, compute_confidence 用。新系は下記の CONFIDENCE_*_THRESHOLD)
CONFIDENCE_HIGH = 90
CONFIDENCE_MEDIUM = 70

# Dispatch1 新閾値: evidence_score からの confidence_level 分類
CONFIDENCE_STRONG_THRESHOLD = 85
CONFIDENCE_MEDIUM_THRESHOLD = 60


class ConfidenceLevel(str, Enum):
    """evidence ベースの 4 段階分類。

    - CONFIRMED_STRONG: 即時 LINE 通知対象 (抽選受付ページそのもの等)
    - CONFIRMED_MEDIUM: DB 保存のみ (Tier B, 段階的に強化されうる)
    - CANDIDATE: 弱いシグナル。保存のみ、通知対象外
    - CONFLICTING: 他ソースと矛盾。要レビュー
    """

    CONFIRMED_STRONG = "confirmed_strong"
    CONFIRMED_MEDIUM = "confirmed_medium"
    CANDIDATE = "candidate"
    CONFLICTING = "conflicting"


# evidence_type ベースの基礎点
_EVIDENCE_BASE = {
    "entry_page": 90,       # 抽選応募ページそのもの
    "product_page": 80,     # 商品ページに抽選記載
    "official_notice": 60,  # 公式ニュース・告知
    "store_notice": 55,     # 店舗ブログ・告知
    "faq_or_guide": 50,     # FAQ / ガイド
    "aggregator": 50,       # 人間が集約したまとめブログ (rare-zaiko 等)。
                            # 単独で confirmed_medium 止まり、cross_source で strong に昇格する想定。
    "search_result": 20,    # 検索結果のみ
    "rss_item": 15,         # RSS タイトルのみ
    "social_post": 10,      # Twitter など
    "unknown": 5,
}


@dataclass
class EvidenceFields:
    """evaluate_evidence() 入力。Candidate + 周辺 context から service 層で構築する。"""

    has_apply_start: bool = False
    has_apply_end: bool = False
    has_result_at: bool = False
    has_purchase_window: bool = False
    has_retailer: bool = False
    has_store: bool = False
    has_product_match: bool = False  # products table hit
    has_url: bool = False
    sales_type_known: bool = False
    cross_source_count: int = 0
    title_only: bool = False
    product_name_ambiguous: bool = False
    conflicting_existing: bool = False


def evaluate_evidence(
    *,
    evidence_type: str,
    fields: EvidenceFields,
) -> tuple[ConfidenceLevel, int]:
    """evidence_type ベース評価で (confidence_level, evidence_score 0-100) を返す。

    base = _EVIDENCE_BASE[evidence_type]
    加点: 応募/結果/購入期間、retailer/store/product_match、cross_source
    減点: title_only / sales_type unknown / 日時欠損 / 商品名曖昧 / conflicting
    """
    score = _EVIDENCE_BASE.get(evidence_type, 5)
    if fields.has_apply_start:
        score += 10
    if fields.has_apply_end:
        score += 5
    if fields.has_result_at:
        score += 5
    if fields.has_purchase_window:
        score += 5
    if fields.has_retailer:
        score += 5
    if fields.has_store:
        score += 3
    if fields.has_product_match:
        score += 5
    if fields.has_url:
        score += 2
    if fields.sales_type_known:
        score += 5
    else:
        score -= 20
    if fields.cross_source_count >= 2:
        score += 10
    elif fields.cross_source_count >= 1:
        score += 5
    if fields.title_only:
        score -= 20
    if fields.product_name_ambiguous:
        score -= 10
    date_missing = not (fields.has_apply_start or fields.has_apply_end)
    if date_missing:
        score -= 15
    if fields.conflicting_existing:
        score -= 25

    score = max(0, min(100, score))
    if fields.conflicting_existing:
        return ConfidenceLevel.CONFLICTING, score
    if score >= CONFIDENCE_STRONG_THRESHOLD:
        return ConfidenceLevel.CONFIRMED_STRONG, score
    if score >= CONFIDENCE_MEDIUM_THRESHOLD:
        return ConfidenceLevel.CONFIRMED_MEDIUM, score
    return ConfidenceLevel.CANDIDATE, score


def map_to_legacy_status(level: ConfidenceLevel) -> str:
    """旧 official_confirmation_status への互換マッピング。

    旧 {confirmed, unconfirmed, conflicting} に落とす。
    medium/candidate はいずれも unconfirmed 相当。
    """
    return {
        ConfidenceLevel.CONFIRMED_STRONG: "confirmed",
        ConfidenceLevel.CONFIRMED_MEDIUM: "unconfirmed",
        ConfidenceLevel.CANDIDATE: "unconfirmed",
        ConfidenceLevel.CONFLICTING: "conflicting",
    }[level]


_EVIDENCE_LABEL = {
    "entry_page": "抽選受付ページ",
    "product_page": "商品ページ",
    "official_notice": "公式告知",
    "store_notice": "店舗告知",
    "faq_or_guide": "FAQ/ガイド",
    "aggregator": "集約まとめ",
    "search_result": "検索結果",
    "rss_item": "RSS",
    "social_post": "SNS",
    "unknown": "出典不明",
}


def build_evidence_summary(
    *,
    evidence_type: str,
    has_apply_period: bool,
    has_result: bool,
    sales_type: str,
) -> str:
    """人間可読の短い要約。evidence_summary カラム向け。"""
    parts: list[str] = []
    parts.append(_EVIDENCE_LABEL.get(evidence_type, evidence_type))
    if has_apply_period:
        parts.append("応募期間明記")
    if has_result:
        parts.append("結果発表あり")
    if sales_type and sales_type != "unknown":
        parts.append(f"種別:{sales_type}")
    return " / ".join(parts)


# ----- Legacy (Phase 1) 互換 API。既存呼び出し互換のため残す。 -----


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
    body_extracted: bool = False,
    title_only: bool = True,
    cross_source_count: int = 0,
) -> int:
    """trust 基礎 → body ボーナス → 情報ボーナス → ペナルティ →
    クロスソース加点 → clamp。"""
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
        score -= 25
    if title_only and not body_extracted:
        score -= 20
    if product_name_ambiguous:
        score -= 10
    if date_missing:
        score -= 15
    if conflicting_existing:
        score -= 15
    if cross_source_count >= 2:
        score += 15
    elif cross_source_count >= 1:
        score += 5
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
