from __future__ import annotations

import logging

from bs4 import BeautifulSoup

from ..lib.normalize import normalize_product_name
from ..lib.snapshot import content_hash
from ..lib.text_clean import clean_text
from .base import Candidate, SourceAdapter
from .http import fetch_text
from .registry import register_adapter

log = logging.getLogger(__name__)
URL = (
    "https://www.amazon.co.jp/s?k=%E3%83%9D%E3%82%B1%E3%83%A2%E3%83%B3%E3%82%AB%E3%83%BC"
    "%E3%83%89%E3%82%B2%E3%83%BC%E3%83%A0+BOX&i=toys"
)

_POKEMON_KEYWORDS = ("ポケモンカード", "ポケカ")


@register_adapter("amazon_search")
class AmazonSearchAdapter(SourceAdapter):
    """Amazon 検索ページから ASIN + 商品名を拾う。

    「予約」「招待制」「発売」kw が含まれる候補を lottery event として返す。
    ASIN ベースで個別商品 URL 生成。sales_type は title から推定。
    """

    def __init__(self, *, html: str | None = None) -> None:
        self._html = html

    async def run(self) -> list[Candidate]:
        html = self._html if self._html is not None else await fetch_text(URL)
        soup = BeautifulSoup(html, "html.parser")
        out: list[Candidate] = []
        seen_asins: set[str] = set()

        for item in soup.select("[data-asin]"):
            asin = item.get("data-asin", "").strip()
            if not asin or asin in seen_asins:
                continue
            seen_asins.add(asin)
            # タイトル: h2 > a > span
            h2 = item.select_one("h2 span")
            if not h2:
                continue
            title = clean_text(h2.get_text())
            if not title or not any(k in title for k in _POKEMON_KEYWORDS):
                continue

            # 販売状態を title から推定
            sales_type = "unknown"
            if "招待制" in title or "招待" in title:
                sales_type = "invitation"
            elif "予約" in title:
                sales_type = "preorder_lottery"
            elif "抽選" in title:
                sales_type = "lottery"
            elif "まもなく発売" in title or "近日発売" in title:
                sales_type = "first_come"

            # sales_type が unknown なら Amazon からは候補化しない (通常在庫販売は除外)
            if sales_type == "unknown":
                continue

            product_name_raw = clean_text(title[:120])
            product_name_normalized = normalize_product_name(title)
            if not product_name_normalized or len(product_name_normalized) < 2:
                continue

            url_full = f"https://www.amazon.co.jp/dp/{asin}"

            out.append(
                Candidate(
                    product_name_raw=product_name_raw,
                    product_name_normalized=product_name_normalized,
                    retailer_name="amazon",
                    sales_type=sales_type,
                    canonical_title=title[:200],
                    source_name="amazon_search",
                    source_url=url_full,
                    source_title=title[:200],
                    raw_snapshot=content_hash(asin),
                    extracted_payload={"asin": asin, "title": title},
                    evidence_type="search_result",
                    product_url=url_full,
                    retailer_event_id=asin,
                )
            )
        return out
