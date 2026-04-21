"""公式/店舗告知タイトルの分類器。

Returns a TitleCategory enum describing the title's nature so adapters
can decide whether to emit a Candidate and with what sales_type.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class TitleCategory(StrEnum):
    LOTTERY_ACTIVE = "lottery_active"        # 抽選応募受付中 (候補化)
    LOTTERY_CLOSED = "lottery_closed"        # 抽選受付終了 (候補化しない)
    LOTTERY_RESULT = "lottery_result"        # 当選者発表 (過去イベ)
    FIRST_COME_ACTIVE = "first_come_active"  # 先着応募受付中
    RELEASE_ANNOUNCE = "release_announce"    # 発売告知のみ (抽選情報なし)
    SALES_METHOD = "sales_method"            # 販売方法について (抽選情報ありの可能性)
    IRRELEVANT = "irrelevant"                # 大会/イベント等、候補化しない


# 過去イベント系キーワード (これらが含まれたら archived 扱い)
_PAST_EVENT_KEYWORDS = (
    "当選者", "当選結果", "結果発表", "受付は終了", "応募受付終了",
    "受付終了", "抽選終了",
)

# 発売告知系 (「X月Y日に発売」「発売決定」)
_RELEASE_ONLY_PATTERNS = (
    re.compile(r"[^抽応]*?が、?\s*\d+月\d+日.*?発売"),
    re.compile(r"発売決定"),
    re.compile(r"発売!"),
    re.compile(r"世界同時発売"),
)

# 抽選応募系 (明示的な応募受付の語彙)
_LOTTERY_ACTIVE_KEYWORDS = (
    "抽選応募", "抽選受付", "抽選販売.*開始", "抽選予約",
    "応募期間", "応募開始", "応募受付開始",
)
_LOTTERY_ACTIVE_RE = re.compile("|".join(_LOTTERY_ACTIVE_KEYWORDS))

# 「抽選販売商品」でも「当選者へのお知らせ」はすでに過去 → _PAST_EVENT_KEYWORDS で先に弾く

# 先着系
_FIRST_COME_KEYWORDS = ("先着応募開始", "先着エントリー", "先着販売.*開始", "先着受付")
_FIRST_COME_RE = re.compile("|".join(_FIRST_COME_KEYWORDS))

# 販売方法告知系
_SALES_METHOD_KEYWORDS = ("販売方法について", "販売について", "販売方法のお知らせ")
_SALES_METHOD_RE = re.compile("|".join(_SALES_METHOD_KEYWORDS))

# 除外: 大会/イベント/GPツアー/チャンピオンシップ/フレンダ等
_IRRELEVANT_KEYWORDS = (
    "チャンピオンズリーグ", "ポケモン GO", "GOポケモン",
    "ポケモンフレンダ", "プレイヤー名鑑", "大会開催",
    "参加者向け", "ガオーレ", "トレッタ", "バトルスコア",
    "ジムバトル", "リモート", "対戦", "もふもふ",
    "GPツアー", "プレゼントキャンペーン",
)


@dataclass
class TitleAnalysis:
    category: TitleCategory
    inferred_sales_type: str  # lottery / preorder_lottery / first_come / numbered_ticket / unknown


def classify_title(title: str) -> TitleAnalysis:
    t = title or ""

    # 1. 過去イベント最優先で弾く
    if any(k in t for k in _PAST_EVENT_KEYWORDS):
        # 「当選者」系は結果発表
        if "当選者" in t or "当選結果" in t or "結果発表" in t:
            return TitleAnalysis(TitleCategory.LOTTERY_RESULT, "lottery")
        return TitleAnalysis(TitleCategory.LOTTERY_CLOSED, "lottery")

    # 2. 大会・イベント系は除外
    if any(k in t for k in _IRRELEVANT_KEYWORDS):
        return TitleAnalysis(TitleCategory.IRRELEVANT, "unknown")

    # 3. 抽選応募受付系
    if _LOTTERY_ACTIVE_RE.search(t) or ("抽選" in t and ("応募" in t or "受付" in t)):
        stype = "lottery"
        if "予約" in t:
            stype = "preorder_lottery"
        return TitleAnalysis(TitleCategory.LOTTERY_ACTIVE, stype)

    # 4. 先着受付
    if _FIRST_COME_RE.search(t):
        return TitleAnalysis(TitleCategory.FIRST_COME_ACTIVE, "first_come")

    # 5. 販売方法告知
    if _SALES_METHOD_RE.search(t):
        return TitleAnalysis(TitleCategory.SALES_METHOD, "unknown")

    # 6. 発売告知のみ
    if any(p.search(t) for p in _RELEASE_ONLY_PATTERNS):
        return TitleAnalysis(TitleCategory.RELEASE_ANNOUNCE, "unknown")

    # 7. その他 → 候補化しない (抽選情報と判断できない)
    return TitleAnalysis(TitleCategory.IRRELEVANT, "unknown")
