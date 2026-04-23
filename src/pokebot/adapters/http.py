from __future__ import annotations

import os
from urllib.parse import urlparse

import httpx

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

# Supabase edge function (fetch-jp) 経由で fetch すべきホスト。
# GHA US ランナーから直接 fetch すると 403 を食うサイト。
# Tokyo region の edge function が代理 fetch することで JP IP で取得する。
# 環境変数 SUPABASE_FETCH_JP_URL + SUPABASE_FETCH_JP_KEY が両方セットされている時のみ有効。
PROXY_HOSTS: frozenset[str] = frozenset(
    {
        "www.yodobashi.com",
        "www.biccamera.com",
        "www.amiami.com",
        "www.amiami.jp",
        "www.amazon.co.jp",
        # 将来追加する adapter もここに足せばよい
        "www.toysrus.co.jp",
        "shop.joshin.co.jp",
        "joshinweb.jp",
        "ec.geo-online.co.jp",
        "www.hmv.co.jp",
        "7net.omni7.jp",
        "www.suruga-ya.jp",
    }
)


def _should_proxy(url: str) -> bool:
    """指定 URL が proxy 経由 fetch 対象か。env 未設定時は False (直接 fetch)。"""
    if not os.environ.get("SUPABASE_FETCH_JP_URL"):
        return False
    if not os.environ.get("SUPABASE_FETCH_JP_KEY"):
        return False
    try:
        host = urlparse(url).hostname or ""
    except Exception:  # noqa: BLE001
        return False
    return host in PROXY_HOSTS


async def fetch_text(url: str, *, timeout: float = 15.0, accept_language: str = "ja") -> str:
    """URL から text を取得。PROXY_HOSTS に該当する host は Supabase edge function 経由で fetch。

    edge function は HTTP status をそのまま返す (403/404 等も通過)。raise_for_status で
    既存と同じ挙動 (2xx 以外は例外) を維持する。
    """
    if _should_proxy(url):
        proxy_url = os.environ["SUPABASE_FETCH_JP_URL"]
        proxy_key = os.environ["SUPABASE_FETCH_JP_KEY"]
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(
                proxy_url,
                params={"url": url},
                headers={"x-proxy-key": proxy_key},
            )
            resp.raise_for_status()
            return resp.text

    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept-Language": accept_language,
    }
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.text
