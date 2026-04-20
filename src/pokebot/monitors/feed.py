from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable

import feedparser
import httpx

from .base import Monitor
from .types import RawItem

Parser = Callable[[feedparser.FeedParserDict], Awaitable[Iterable[RawItem]]]


class FeedMonitor(Monitor):
    def __init__(self, id_: str, url: str, interval_sec: int, parser: Parser) -> None:
        self.id = id_
        self.url = url
        self.interval_sec = interval_sec
        self._parser = parser

    async def fetch(self) -> Iterable[RawItem]:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(self.url)
            resp.raise_for_status()
        feed = feedparser.parse(resp.text)
        return list(await self._parser(feed))
