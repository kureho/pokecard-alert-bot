from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..monitors.types import RawItem

BASE = "https://www.pokemon-card.com"
NEW_PRODUCT_KEYWORDS = ("発売", "新弾", "拡張パック", "ハイクラスパック", "強化拡張パック")


def _classify(title: str) -> str:
    if any(k in title for k in NEW_PRODUCT_KEYWORDS):
        return "new_product"
    return "announcement"


async def news_list(html: str) -> list[RawItem]:
    soup = BeautifulSoup(html, "html.parser")
    items: list[RawItem] = []
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
        items.append(
            RawItem(
                source="pokemon_card_news",
                raw_title=title,
                url=urljoin(BASE, href),
                kind_hint=_classify(title),
            )
        )
    return items
