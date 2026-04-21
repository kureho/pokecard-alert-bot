from __future__ import annotations

import httpx

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


async def fetch_text(url: str, *, timeout: float = 15.0, accept_language: str = "ja") -> str:
    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept-Language": accept_language,
    }
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.text
