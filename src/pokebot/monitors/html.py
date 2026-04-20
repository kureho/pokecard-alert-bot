from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable

import httpx

from .base import Monitor
from .types import RawItem

Parser = Callable[[str], Awaitable[Iterable[RawItem]]]


class HtmlMonitor(Monitor):
    USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    )

    def __init__(self, id_: str, url: str, interval_sec: int, parser: Parser) -> None:
        self.id = id_
        self.url = url
        self.interval_sec = interval_sec
        self._parser = parser

    async def fetch(self) -> Iterable[RawItem]:
        headers = {"User-Agent": self.USER_AGENT, "Accept-Language": "ja"}
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(self.url, headers=headers)
            resp.raise_for_status()
            return list(await self._parser(resp.text))
