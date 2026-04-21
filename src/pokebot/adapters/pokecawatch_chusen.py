from __future__ import annotations

import logging
import re
from datetime import datetime
from time import mktime

import feedparser

from ..lib.body_extractor import extract_body_info
from ..lib.normalize import normalize_product_name
from ..lib.snapshot import content_hash
from ..lib.text_clean import clean_text
from ..lib.title_classifier import TitleCategory, classify_title
from .base import Candidate, SourceAdapter
from .http import fetch_text
from .registry import register_adapter

log = logging.getLogger(__name__)
FEED_URL = "https://pokecawatch.com/category/%E6%8A%BD%E9%81%B8%E3%83%BB%E4%BA%88%E7%B4%84%E6%83%85%E5%A0%B1/feed"

_TITLE_PREFIX_RE = re.compile(r"^【[^】]+】\s*")
_SUFFIX_PATTERNS = ("抽選・予約情報", "抽選予約情報", "抽選情報")


def _strip_pokecawatch_decorations(s: str) -> str:
    s = _TITLE_PREFIX_RE.sub("", s)
    for suffix in _SUFFIX_PATTERNS:
        if s.endswith(suffix):
            s = s[: -len(suffix)].strip()
            break
    return s


@register_adapter("pokecawatch_chusen")
class PokecawatchChusenAdapter(SourceAdapter):
    """ポケカウォッチ 抽選・予約情報カテゴリ RSS。

    1 entry = 1 商品。title「【ポケカ】{商品名} 抽選・予約情報」から商品名を抽出。
    sales_type は title_classifier 経由で判定 (多くは lottery or preorder_lottery)。
    """

    def __init__(
        self,
        *,
        xml: str | None = None,
        body_fetcher=None,
        max_body_fetch: int = 10,
    ) -> None:
        self._xml = xml
        self._body_fetcher = body_fetcher
        self._max_body_fetch = max_body_fetch

    async def run(self) -> list[Candidate]:
        xml = self._xml if self._xml is not None else await fetch_text(FEED_URL)
        parsed = feedparser.parse(xml)
        out: list[Candidate] = []
        fetched = 0
        for e in parsed.entries[:30]:
            title = (e.get("title") or "").strip()
            link = (e.get("link") or "").split("?")[0]  # utm 削除
            if not title or not link:
                continue
            analysis = classify_title(title)
            # pokecawatch は抽選・予約情報カテゴリの RSS そのものなので、
            # タイトル語彙が generic でも LOTTERY 扱いで通す。過去イベントのみ除外。
            if analysis.category in (
                TitleCategory.LOTTERY_CLOSED,
                TitleCategory.LOTTERY_RESULT,
            ):
                continue

            # タイトルから 「【ポケカ】」prefix + 「抽選・予約情報」suffix を削除
            core = _strip_pokecawatch_decorations(title)
            product_name_raw = clean_text(core)
            product_name_normalized = normalize_product_name(core)
            if not product_name_normalized or len(product_name_normalized) < 2:
                continue

            ts = None
            if getattr(e, "published_parsed", None):
                ts = datetime.fromtimestamp(mktime(e.published_parsed))

            # sales_type: analysis 優先、デフォルト lottery (カテゴリ名が抽選)
            sales_type = analysis.inferred_sales_type
            if sales_type == "unknown":
                sales_type = "lottery"

            # 本文 fetch: body から応募期間/結果発表を取得
            body_info = None
            body_html = None
            if fetched < self._max_body_fetch:
                try:
                    body_html = (
                        await self._body_fetcher(link)
                        if self._body_fetcher
                        else await fetch_text(link)
                    )
                    body_info = extract_body_info(body_html)
                    fetched += 1
                except Exception as exc:  # noqa: BLE001
                    log.warning("pokecawatch body fetch failed for %s: %s", link, exc)

            apply_start = body_info.apply_start_at if body_info else None
            apply_end = body_info.apply_end_at if body_info else None
            result_at = body_info.result_at if body_info else None
            purchase_start = body_info.purchase_start_at if body_info else None
            purchase_end = body_info.purchase_end_at if body_info else None
            purchase_limit = body_info.purchase_limit_text if body_info else None
            conditions = body_info.conditions_text if body_info else None

            if body_info and body_info.product_name:
                # body の product_name も同じ接頭辞/接尾辞パターンを含み得るので strip を適用
                body_core = _strip_pokecawatch_decorations(body_info.product_name)
                prod_from_body = normalize_product_name(body_core)
                if prod_from_body and len(prod_from_body) >= 2:
                    product_name_normalized = prod_from_body
                    product_name_raw = clean_text(body_core)

            snapshot_src = body_html if body_html else (title + "|" + link)

            out.append(
                Candidate(
                    product_name_raw=product_name_raw,
                    product_name_normalized=product_name_normalized,
                    retailer_name="pokecawatch",  # aggregator 扱い
                    sales_type=sales_type,
                    canonical_title=title,
                    apply_start_at=apply_start,
                    apply_end_at=apply_end,
                    result_at=result_at,
                    purchase_start_at=purchase_start,
                    purchase_end_at=purchase_end,
                    purchase_limit_text=purchase_limit,
                    conditions_text=conditions,
                    source_name="pokecawatch_chusen",
                    source_url=link,
                    source_title=title,
                    source_published_at=ts,
                    raw_snapshot=content_hash(snapshot_src),
                    extracted_payload={
                        "title": title,
                        "url": link,
                        "body_fetched": body_info is not None,
                        "body_score": body_info.score if body_info else 0,
                    },
                    evidence_type="rss_item",
                )
            )
        return out
