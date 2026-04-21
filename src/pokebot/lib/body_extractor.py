"""候補の source_url から記事本文を fetch し、応募期間等の具体情報を抽出する。

ページ構造は各ソースで異なるが、以下の共通戦略を採る:
1. HTML を plain text に近い形で reduce (script/style/nav 除去)
2. ラベル語彙 ("応募期間"、"抽選応募期間"、"結果発表" 等) の直後テキストから日時抽出
3. 見つからなかったフィールドは None のまま
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from bs4 import BeautifulSoup

from .jp_datetime import parse_jp_datetime
from .text_clean import clean_text

# ラベル → 対象フィールド
_LABEL_FIELDS = [
    # (label, field_key, is_range)
    ("抽選応募期間", "apply", True),
    ("応募期間", "apply", True),
    ("応募受付期間", "apply", True),
    ("応募受付", "apply", True),
    ("抽選結果発表", "result", False),
    ("結果発表", "result", False),
    ("当選発表", "result", False),
    ("購入期間", "purchase", True),
    ("販売期間", "purchase", True),
    ("お渡し期間", "purchase", True),
    ("お支払い期間", "purchase", True),
]

_CONDITION_LABELS = [
    "購入制限", "お一人様", "1人1点", "お一人さま", "1アカウント",
    "ご購入制限", "購入条件",
]


@dataclass
class ExtractedBody:
    apply_start_at: datetime | None = None
    apply_end_at: datetime | None = None
    result_at: datetime | None = None
    purchase_start_at: datetime | None = None
    purchase_end_at: datetime | None = None
    purchase_limit_text: str | None = None
    conditions_text: str | None = None
    body_text: str = ""

    @property
    def has_any_date(self) -> bool:
        return any(
            v is not None for v in (
                self.apply_start_at, self.apply_end_at, self.result_at,
                self.purchase_start_at, self.purchase_end_at,
            )
        )

    @property
    def score(self) -> int:
        """抽出できたフィールド数に応じた +値。confidence計算のヒント。"""
        n = 0
        if self.apply_start_at:
            n += 1
        if self.apply_end_at:
            n += 1
        if self.result_at:
            n += 1
        if self.purchase_start_at:
            n += 1
        if self.purchase_end_at:
            n += 1
        if self.purchase_limit_text:
            n += 1
        return n


def _strip_chrome(soup: BeautifulSoup) -> None:
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside"]):
        tag.decompose()


def _find_range(text_after: str) -> tuple[datetime | None, datetime | None]:
    """'5月10日 14:00 〜 5月14日 23:59' 形式を想定。範囲の2点を返す。"""
    # 範囲セパレータを split
    seps = ["〜", "～", "~", " から ", "から", " to "]
    for s in seps:
        if s in text_after:
            left, right = text_after.split(s, 1)
            return parse_jp_datetime(left), parse_jp_datetime(right)
    # セパレータ無し → 単一日時のみ
    return parse_jp_datetime(text_after), None


def extract_body_info(html: str) -> ExtractedBody:
    soup = BeautifulSoup(html, "html.parser")
    _strip_chrome(soup)
    text = clean_text(soup.get_text(" "))
    result = ExtractedBody(body_text=text)

    for label, field, is_range in _LABEL_FIELDS:
        idx = text.find(label)
        if idx < 0:
            continue
        # ラベル後の 120 文字 を対象
        after = text[idx + len(label) : idx + len(label) + 120]
        if is_range:
            start, end = _find_range(after)
            if field == "apply":
                if start and result.apply_start_at is None:
                    result.apply_start_at = start
                if end and result.apply_end_at is None:
                    result.apply_end_at = end
            elif field == "purchase":
                if start and result.purchase_start_at is None:
                    result.purchase_start_at = start
                if end and result.purchase_end_at is None:
                    result.purchase_end_at = end
        else:
            dt = parse_jp_datetime(after)
            if dt and field == "result" and result.result_at is None:
                result.result_at = dt

    # 条件文抽出 (先頭から該当ラベル周辺 200 文字抽出)
    for label in _CONDITION_LABELS:
        idx = text.find(label)
        if idx >= 0:
            snippet = text[max(0, idx - 10) : idx + 120].strip()
            if result.conditions_text is None:
                result.conditions_text = snippet
            break

    return result
