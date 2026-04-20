from __future__ import annotations

from datetime import datetime
from time import mktime

import feedparser

from ..monitors.types import RawItem


def _classify(title: str) -> str:
    if "抽選" in title:
        return "lottery_open"
    if "再販" in title or "入荷" in title:
        return "restock"
    if any(k in title for k in ("発売", "新弾")):
        return "new_product"
    return "announcement"


# NOTE: Entry structure follows RSS 2.0. Real feed field names may need
# verification once the actual RSS source URL is confirmed.
async def feed(parsed: feedparser.FeedParserDict) -> list[RawItem]:
    items: list[RawItem] = []
    for entry in parsed.entries[:30]:
        title = (entry.get("title") or "").strip()
        link = entry.get("link") or ""
        if not title or not link:
            continue
        ts = None
        if getattr(entry, "published_parsed", None):
            ts = datetime.fromtimestamp(mktime(entry.published_parsed))
        items.append(
            RawItem(
                source="pokeca_sokuhou",
                raw_title=title,
                url=link,
                kind_hint=_classify(title),
                source_ts=ts,
            )
        )
    return items
