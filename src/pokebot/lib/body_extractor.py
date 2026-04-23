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


def _infer_sales_type_from_body(text: str) -> str:
    """本文テキストから sales_type を推定。優先順は上から下。

    title 由来で SALES_METHOD (販売方法について) と分類された記事では、title から
    抽選/先着を判断できないため、本文で最終判定する。
    """
    # 招待: Amazon 等の「招待リクエスト」型。他より特殊なので先に判定。
    if "招待" in text and "リクエスト" in text:
        return "invitation"
    # 抽選系 (先着より優先): 本文メインが抽選で落選者に先着がおまけ、のパターンを考慮
    if "抽選" in text and ("応募" in text or "受付" in text or "販売" in text):
        if "予約" in text:
            return "preorder_lottery"
        return "lottery"
    # 整理券
    if "整理券" in text or "番号札" in text:
        return "numbered_ticket"
    # 先着
    if "先着" in text:
        return "first_come"
    return "unknown"


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
    product_name: str | None = None
    # 本文から推定した販売方式。title 由来の unknown を上書きできる。
    # 値: lottery / preorder_lottery / first_come / numbered_ticket / invitation / unknown
    inferred_sales_type: str = "unknown"

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


def _extract_product_name(soup: BeautifulSoup) -> str | None:
    """h1 優先、無ければ <title> からサイト名部分を除去して返す。"""
    h1 = soup.select_one("h1")
    if h1:
        raw_h1 = clean_text(h1.get_text(" "))
        if raw_h1 and len(raw_h1) < 200:
            return raw_h1
    title_tag = soup.select_one("title")
    if title_tag:
        raw_title = clean_text(title_tag.get_text(" "))
        if raw_title:
            # 「サイト名」部分を削除 (例: 「アビスアイ｜ポケモンセンター」→ 「アビスアイ」)
            for sep in ("｜", "|", " - ", " — ", "│"):
                if sep in raw_title:
                    raw_title = raw_title.split(sep, 1)[0].strip()
                    break
            if raw_title and len(raw_title) < 200:
                return raw_title
    return None


def extract_body_info(html: str) -> ExtractedBody:
    soup = BeautifulSoup(html, "html.parser")
    # product_name は chrome 除去前に取得 (title タグは head 内なので本来残るが、
    # h1 が nav/header 内にあることは稀。素直に strip 前に採る)
    product_name = _extract_product_name(soup)
    _strip_chrome(soup)
    text = clean_text(soup.get_text(" "))
    result = ExtractedBody(body_text=text, product_name=product_name)

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

    result.inferred_sales_type = _infer_sales_type_from_body(text)

    return result
