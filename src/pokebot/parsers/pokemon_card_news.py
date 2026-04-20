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


# NOTE: CSS selectors match synthetic test fixture.
# Adjust after first live fetch of the real news listing page.
async def news_list(html: str) -> list[RawItem]:
    soup = BeautifulSoup(html, "html.parser")
    items: list[RawItem] = []
    for a in soup.select("li.news-item a[href]"):
        title = a.get_text(strip=True)
        href = a["href"]
        if not title:
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
