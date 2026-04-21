from __future__ import annotations

import logging
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..lib.normalize import normalize_product_name
from ..lib.snapshot import content_hash
from ..lib.text_clean import clean_text
from .base import Candidate, SourceAdapter
from .http import fetch_text
from .registry import register_adapter

log = logging.getLogger(__name__)
BASE = "https://www.yodobashi.com"
URL = f"{BASE}/ec/special/other/54666/"


@register_adapter("yodobashi_lottery")
class YodobashiLotteryAdapter(SourceAdapter):
    """ヨドバシ抽選ページ。US IP からは 403 Forbidden。例外は上位層で catch。"""

    def __init__(self, *, html: str | None = None) -> None:
        self._html = html

    async def run(self) -> list[Candidate]:
        html = self._html if self._html is not None else await fetch_text(URL)
        soup = BeautifulSoup(html, "html.parser")
        out: list[Candidate] = []
        # ヨドバシ抽選一覧のアンカー抽出（ポケモンカード関連タイトルのみ）
        for a in soup.select("a[href]"):
            title = clean_text(a.get_text())
            if not title or ("ポケモン" not in title and "ポケカ" not in title):
                continue
            href = a.get("href") or ""
            if not href:
                continue
            url = urljoin(BASE, href)
            out.append(Candidate(
                product_name_raw=title,
                product_name_normalized=normalize_product_name(title),
                retailer_name="yodobashi",
                sales_type="lottery",
                canonical_title=title,
                source_name="yodobashi_lottery",
                source_url=url,
                source_title=title,
                raw_snapshot=content_hash(title + "|" + url),
                extracted_payload={"title": title, "url": url},
            ))
        return out
