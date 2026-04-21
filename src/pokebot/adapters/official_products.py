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
_RELEASE_KEYWORDS = ("発売", "新弾", "リリース")
_TYPE_MAP = [
    ("強化拡張パック", "強化拡張パック"),
    ("ハイクラスパック", "ハイクラスパック"),
    ("拡張パック", "拡張パック"),
    ("プロモパック", "プロモパック"),
    ("スターターセット", "スターターセット"),
    ("スペシャルBOX", "スペシャルBOX"),
    ("スタートデッキ", "スタートデッキ"),
]


def _detect_product_type(title: str) -> str | None:
    for kw, t in _TYPE_MAP:
        if kw in title:
            return t
    return None


@register_adapter("pokemon_official_products")
class PokemonOfficialProductsAdapter(SourceAdapter):
    """商品マスター生成用。公式 news から '発売' 告知を抽出して candidate として返す。

    service 層で ProductRepo に upsert する。
    lottery_event にはならないが Candidate を product_master_hint として payload に詰める。
    """
    url = f"{BASE}/info/"

    def __init__(self, *, html: str | None = None) -> None:
        self._html = html

    async def run(self) -> list[Candidate]:
        html = self._html if self._html is not None else await fetch_text(self.url)
        soup = BeautifulSoup(html, "html.parser")
        out: list[Candidate] = []
        for a in soup.select("li.List_item a.List_item_inner[href]"):
            href = a.get("href") or ""
            img = a.select_one(".List_title img[alt]")
            title = (img.get("alt") or "").strip() if img else ""
            if not title or not href:
                continue
            if not any(k in title for k in _RELEASE_KEYWORDS):
                continue
            release_dt = parse_jp_datetime(title)
            product_type = _detect_product_type(title)
            url = urljoin(BASE, href)

            out.append(Candidate(
                product_name_raw=clean_text(title),
                product_name_normalized=normalize_product_name(title),
                retailer_name="pokemon_official",
                sales_type="unknown",
                canonical_title=title,
                source_name="pokemon_official_products",
                source_url=url,
                source_title=title,
                raw_snapshot=content_hash(title + "|" + url),
                extracted_payload={
                    "is_product_master_hint": True,
                    "release_date": release_dt.date().isoformat() if release_dt else None,
                    "product_type": product_type,
                    "official_product_url": url,
                },
            ))
        return out
