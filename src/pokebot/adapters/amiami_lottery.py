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
URL = "https://www.amiami.com/jp/event/lottery"


@register_adapter("amiami_lottery")
class AmiamiLotteryAdapter(SourceAdapter):
    """amiami の抽選ページ。US IP からは 403 で失敗する前提。Phase 2 で proxy 検討。"""

    def __init__(self, *, html: str | None = None) -> None:
        self._html = html

    async def run(self) -> list[Candidate]:
        html = self._html if self._html is not None else await fetch_text(URL)
        soup = BeautifulSoup(html, "html.parser")
        out: list[Candidate] = []
        # ポケモン関連のリンクを広く拾う (構造はページに依存。fixture なしなので保守的)
        for a in soup.select("a[href]"):
            title = clean_text(a.get_text())
            if not title or ("ポケモン" not in title and "ポケカ" not in title):
                continue
            href = a.get("href") or ""
            if not href:
                continue
            _url = href if href.startswith("http") else f"https://www.amiami.com{href}"
            out.append(
                Candidate(
                    product_name_raw=title,
                    product_name_normalized=normalize_product_name(title),
                    retailer_name="amiami",
                    sales_type="lottery",  # 抽選ページからの抽出と仮定
                    canonical_title=title,
                    source_name="amiami_lottery",
                    source_url=_url,
                    source_title=title,
                    raw_snapshot=content_hash(title + "|" + href),
                    extracted_payload={"title": title, "url": href},
                    evidence_type="entry_page",
                    application_url=_url,
                    entry_method="lottery_page",
                )
            )
        return out
