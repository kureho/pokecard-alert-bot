"""楽天ブックス ポケモンカードゲーム抽選受付ページ adapter。

`books.rakuten.co.jp/event/game/card/entry/` を監視。

状態:
- 受付中: apply_start_at / apply_end_at / result_at を抽出、1 candidate 返す
- 受付終了: sale_status_hint='ended' で 1 candidate (過去情報として記録)
- 完全 empty: 0 candidate

エンコーディング EUC-JP。httpx デフォルトの encoding 判定は効かないので content.decode で明示。
"""
from __future__ import annotations

import logging
import re
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from ..lib.normalize import normalize_product_name
from ..lib.snapshot import content_hash
from ..lib.text_clean import clean_text
from .base import Candidate, SourceAdapter
from .http import DEFAULT_USER_AGENT
from .registry import register_adapter

log = logging.getLogger(__name__)
BASE = "https://books.rakuten.co.jp"
URL = f"{BASE}/event/game/card/entry/"

# 「2026/1/23（金） 10：00」形式
_DATE_RE = re.compile(
    r"(\d{4})/(\d{1,2})/(\d{1,2})[^0-9]{0,4}(\d{1,2})[：:](\d{1,2})"
)
# 「抽選受付期間 ... ～ ...」セクションを取るための分割
_PERIOD_SECTION_RE = re.compile(
    r"抽選受付期間[\s　]*([^※。]{10,120}?)(?:\s*当選連絡|$)", re.S
)
_RESULT_LINE_RE = re.compile(r"当選連絡予定日[：:]\s*(\d{4}/\d{1,2}/\d{1,2})")


def _parse_dt(match) -> datetime | None:
    try:
        if match.lastindex == 5:
            y, mo, d, h, mi = (
                match.group(1),
                match.group(2),
                match.group(3),
                match.group(4),
                match.group(5),
            )
            return datetime(int(y), int(mo), int(d), int(h), int(mi))
        else:
            y, mo, d = match.group(1), match.group(2), match.group(3)
            return datetime(int(y), int(mo), int(d))
    except (ValueError, TypeError):
        return None


def _extract_period(text: str) -> tuple[datetime | None, datetime | None]:
    """抽選受付期間セクションから start/end を抽出。"""
    section = _PERIOD_SECTION_RE.search(text)
    if not section:
        return None, None
    body = section.group(1)
    # ～ / 〜 / ~ で split
    parts = re.split(r"[～〜~]", body, maxsplit=1)
    start_dt = None
    end_dt = None
    if parts:
        m = _DATE_RE.search(parts[0])
        if m:
            start_dt = _parse_dt(m)
    if len(parts) >= 2:
        m = _DATE_RE.search(parts[1])
        if m:
            end_dt = _parse_dt(m)
    return start_dt, end_dt


def _extract_result_date(text: str) -> datetime | None:
    m = _RESULT_LINE_RE.search(text)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y/%m/%d")
    except ValueError:
        return None


async def _fetch_euc_jp(url: str) -> str:
    """EUC-JP 固定でフェッチ。httpx の encoding auto-detect を上書き。"""
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        resp = await client.get(
            url,
            headers={
                "User-Agent": DEFAULT_USER_AGENT,
                "Accept-Language": "ja",
            },
        )
        resp.raise_for_status()
        return resp.content.decode("euc-jp", errors="replace")


@register_adapter("rakuten_books_entry")
class RakutenBooksEntryAdapter(SourceAdapter):
    """楽天ブックス ポケモンカードゲーム抽選受付ページ。

    受付中 or 終了直後の情報を 1 candidate で返す。商品別ではなく楽天ブックス全体の
    "ポケモンカードゲーム抽選枠" として扱う。商品特定は他 adapter のクロスソース参照で補完する。
    """

    def __init__(self, *, html: str | None = None) -> None:
        self._html = html

    async def run(self) -> list[Candidate]:
        html = self._html if self._html is not None else await _fetch_euc_jp(URL)
        soup = BeautifulSoup(html, "html.parser")
        # script/style/nav 等除去した本文
        for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
            tag.decompose()
        text = clean_text(soup.get_text(" ", strip=True))

        if not text:
            return []

        apply_start, apply_end = _extract_period(text)
        result_at = _extract_result_date(text)

        is_ended = "受付は終了" in text
        is_accepting = not is_ended and (
            apply_start is not None or apply_end is not None
        )

        # 期間情報も無く、受付中判定もできない場合は candidate 化しない
        if apply_start is None and apply_end is None and not is_ended:
            return []

        sale_status_hint = (
            "ended"
            if is_ended
            else ("accepting" if is_accepting else "unknown")
        )

        # 商品名は汎用 (楽天ブックスは商品別ではなく "ポケモンカードゲーム抽選枠" で受付)
        product_name_raw = "ポケモンカードゲーム (楽天ブックス抽選)"
        # normalize_product_name は KNOWN_PRODUCTS に該当なければ空文字になり得るので fallback する
        product_name_normalized = (
            normalize_product_name("ポケモンカードゲーム")
            or "ポケモンカードゲーム"
        )

        return [
            Candidate(
                product_name_raw=product_name_raw,
                product_name_normalized=product_name_normalized,
                retailer_name="rakuten_books",
                sales_type="lottery",
                canonical_title="楽天ブックス ポケモンカードゲーム抽選",
                apply_start_at=apply_start,
                apply_end_at=apply_end,
                result_at=result_at,
                source_name="rakuten_books_entry",
                source_url=URL,
                source_title="楽天ブックス ポケモンカードゲーム抽選受付ページ",
                raw_snapshot=content_hash(text[:800]),
                application_url=URL,
                entry_method="lottery_page",
                sale_status_hint=sale_status_hint,
                evidence_type="entry_page",
                raw_text_excerpt=text[:300],
                canonical_fields={
                    "is_ended": is_ended,
                    "is_accepting": is_accepting,
                },
                extracted_payload={
                    "is_ended": is_ended,
                    "is_accepting": is_accepting,
                    "url": URL,
                },
            )
        ]
