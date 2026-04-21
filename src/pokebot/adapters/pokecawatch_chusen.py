from __future__ import annotations

import logging
import re
from datetime import datetime
from time import mktime

import feedparser

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


@register_adapter("pokecawatch_chusen")
class PokecawatchChusenAdapter(SourceAdapter):
    """ポケカウォッチ 抽選・予約情報カテゴリ RSS。

    1 entry = 1 商品。title「【ポケカ】{商品名} 抽選・予約情報」から商品名を抽出。
    sales_type は title_classifier 経由で判定 (多くは lottery or preorder_lottery)。
    """

    def __init__(self, *, xml: str | None = None) -> None:
        self._xml = xml

    async def run(self) -> list[Candidate]:
        xml = self._xml if self._xml is not None else await fetch_text(FEED_URL)
        parsed = feedparser.parse(xml)
        out: list[Candidate] = []
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

            # タイトルから 「【ポケカ】」prefix を除去 → 商品名候補
            core = _TITLE_PREFIX_RE.sub("", title)
            # 「抽選・予約情報」「抽選予約情報」 suffix を削除
            for suffix in ("抽選・予約情報", "抽選予約情報", "抽選情報"):
                if core.endswith(suffix):
                    core = core[: -len(suffix)].strip()
                    break

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

            out.append(
                Candidate(
                    product_name_raw=product_name_raw,
                    product_name_normalized=product_name_normalized,
                    retailer_name="pokecawatch",  # aggregator 扱い
                    sales_type=sales_type,
                    canonical_title=title,
                    source_name="pokecawatch_chusen",
                    source_url=link,
                    source_title=title,
                    source_published_at=ts,
                    raw_snapshot=content_hash(title + "|" + link),
                    extracted_payload={"title": title, "url": link},
                )
            )
        return out
