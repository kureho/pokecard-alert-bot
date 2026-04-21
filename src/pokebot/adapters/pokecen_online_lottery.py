from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..lib.jp_datetime import parse_jp_datetime
from ..lib.normalize import normalize_product_name
from ..lib.snapshot import content_hash
from ..lib.text_clean import clean_text
from .base import Candidate, SourceAdapter
from .http import fetch_text
from .registry import register_adapter

BASE = "https://www.pokemoncenter-online.com"
URL = f"{BASE}/lottery/apply.html"


@register_adapter("pokemoncenter_online_lottery")
class PokecenOnlineLotteryAdapter(SourceAdapter):
    def __init__(self, *, html: str | None = None) -> None:
        self._html = html

    async def run(self) -> list[Candidate]:
        html = self._html if self._html is not None else await fetch_text(URL)
        soup = BeautifulSoup(html, "html.parser")
        candidates: list[Candidate] = []

        # "抽選がありません" empty state の検出
        text = soup.get_text(" ", strip=True)
        if "抽選がありません" in text:
            return candidates

        # 抽選商品のテーブル (table.no_size or section 内 anchor)
        for row in soup.select("table.no_size tr, section.lottery li"):
            a = row.select_one("a[href]")
            if not a:
                continue
            title = clean_text(a.get_text())
            href = a.get("href") or ""
            if not title or not href:
                continue

            # 周辺テキストから日付を拾う
            ctx = clean_text(row.get_text())
            apply_start = parse_jp_datetime(ctx)
            url = urljoin(BASE, href)

            candidates.append(Candidate(
                product_name_raw=title,
                product_name_normalized=normalize_product_name(title),
                retailer_name="pokemoncenter_online",
                sales_type="lottery",
                canonical_title=title,
                apply_start_at=apply_start,
                source_name="pokemoncenter_online_lottery",
                source_url=url,
                source_title=title,
                raw_snapshot=content_hash(ctx + "|" + url),
                extracted_payload={"row_text": ctx, "url": url},
                evidence_type="entry_page",
                application_url=url,
                entry_method="lottery_page",
                raw_text_excerpt=ctx[:500],
            ))
        return candidates
