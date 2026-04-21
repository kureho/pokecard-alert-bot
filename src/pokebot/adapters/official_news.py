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

BASE = "https://www.pokemon-card.com"

# タイトルから「抽選」「先着」等のシグナルを拾う
_SALES_TYPE_KEYWORDS = [
    ("抽選販売", "lottery"),
    ("抽選予約", "preorder_lottery"),
    ("抽選", "lottery"),
    ("先着順", "first_come"),
    ("先着", "first_come"),
    ("整理券", "numbered_ticket"),
    ("招待制", "invitation"),
]

_RELEASE_KEYWORDS = ("発売", "新弾", "リリース")


def _detect_sales_type(title: str) -> str:
    for kw, stype in _SALES_TYPE_KEYWORDS:
        if kw in title:
            return stype
    return "unknown"


@register_adapter("pokemon_official_news")
class PokemonOfficialNewsAdapter(SourceAdapter):
    url = f"{BASE}/info/"

    def __init__(self, *, html: str | None = None) -> None:
        """html: テスト注入用。未指定なら fetch する。"""
        self._html = html

    async def run(self) -> list[Candidate]:
        html = self._html if self._html is not None else await fetch_text(self.url)
        soup = BeautifulSoup(html, "html.parser")
        candidates: list[Candidate] = []
        for a in soup.select("li.List_item a.List_item_inner[href]"):
            href = a.get("href") or ""
            img = a.select_one(".List_title img[alt]")
            title = (img.get("alt") or "").strip() if img else ""
            if not title:
                body = a.select_one(".List_body")
                if body:
                    for el in body.select(".Calendar_Label, .Date"):
                        el.extract()
                    title = body.get_text(strip=True)
            if not title or not href:
                continue
            url = urljoin(BASE, href)

            # 公式 news 内でも抽選/販売方法告知 or 商品発売告知を対象にする
            has_sales_keyword = any(k in title for k, _ in _SALES_TYPE_KEYWORDS)
            has_release_keyword = any(k in title for k in _RELEASE_KEYWORDS)
            if not (has_sales_keyword or has_release_keyword):
                continue

            sales_type = _detect_sales_type(title) if has_sales_keyword else "unknown"
            apply_date = parse_jp_datetime(title)
            product_name_raw = clean_text(title)
            product_name_normalized = normalize_product_name(title)

            candidates.append(Candidate(
                product_name_raw=product_name_raw,
                product_name_normalized=product_name_normalized,
                retailer_name="pokemoncenter_online",  # 公式ニュースはポケセンオンラインの告知が多い
                sales_type=sales_type,
                canonical_title=title,
                apply_start_at=apply_date,
                source_name="pokemon_official_news",
                source_url=url,
                source_title=title,
                raw_snapshot=content_hash(title + "|" + url),
                extracted_payload={"title": title, "url": url},
            ))
        return candidates
