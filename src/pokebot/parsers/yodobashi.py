from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..monitors.types import RawItem

BASE = "https://www.yodobashi.com"


# NOTE: CSS selectors match synthetic test fixture.
# Adjust after first live fetch of the real lottery listing page.
async def lottery_list(html: str) -> list[RawItem]:
    soup = BeautifulSoup(html, "html.parser")
    items: list[RawItem] = []
    for card in soup.select("li.pList_item"):
        a = card.select_one("a.js_productListPostTag")
        if not a:
            continue
        title = (a.get_text(strip=True) or "").strip()
        href = a.get("href") or ""
        if not title or not href:
            continue
        items.append(RawItem(
            source="yodobashi",
            raw_title=title,
            url=urljoin(BASE, href),
            kind_hint="lottery_open",
        ))
    return items
