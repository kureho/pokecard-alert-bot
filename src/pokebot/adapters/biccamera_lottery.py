from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..lib.normalize import normalize_product_name
from ..lib.snapshot import content_hash
from ..lib.text_clean import clean_text
from .base import Candidate, SourceAdapter
from .http import fetch_text
from .registry import register_adapter

BASE = "https://www.biccamera.com"
URL = f"{BASE}/bc/i/card/pokemoncard/index.jsp"


@register_adapter("biccamera_lottery")
class BiccameraLotteryAdapter(SourceAdapter):
    def __init__(self, *, html: str | None = None) -> None:
        self._html = html

    async def run(self) -> list[Candidate]:
        html = self._html if self._html is not None else await fetch_text(URL)
        soup = BeautifulSoup(html, "html.parser")
        out: list[Candidate] = []
        for a in soup.select("a[href]"):
            title = clean_text(a.get_text())
            if not title or "抽選" not in title:
                continue
            href = a.get("href") or ""
            url = urljoin(BASE, href)
            out.append(Candidate(
                product_name_raw=title,
                product_name_normalized=normalize_product_name(title),
                retailer_name="biccamera",
                sales_type="lottery",
                canonical_title=title,
                source_name="biccamera_lottery",
                source_url=url,
                source_title=title,
                raw_snapshot=content_hash(title + "|" + url),
                extracted_payload={"title": title, "url": url},
                evidence_type="entry_page",
                application_url=url,
                entry_method="lottery_page",
            ))
        return out
