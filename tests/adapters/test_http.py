"""adapters.http.fetch_text の proxy ルーティング検証。

PROXY_HOSTS に該当する URL かつ SUPABASE_FETCH_JP_URL + SUPABASE_FETCH_JP_KEY が
両方セットされている時だけ Supabase edge function 経由で fetch する。
"""

from __future__ import annotations

import pytest

from pokebot.adapters.http import PROXY_HOSTS, fetch_text


@pytest.mark.asyncio
async def test_direct_fetch_when_proxy_not_configured(httpx_mock, monkeypatch):
    """env 未設定時は直接 fetch (従来動作)。"""
    monkeypatch.delenv("SUPABASE_FETCH_JP_URL", raising=False)
    monkeypatch.delenv("SUPABASE_FETCH_JP_KEY", raising=False)

    httpx_mock.add_response(
        url="https://www.yodobashi.com/test",
        text="<html>direct</html>",
    )

    result = await fetch_text("https://www.yodobashi.com/test")
    assert result == "<html>direct</html>"

    req = httpx_mock.get_requests()[0]
    assert "x-proxy-key" not in req.headers


@pytest.mark.asyncio
async def test_proxy_fetch_for_allowed_host(httpx_mock, monkeypatch):
    """PROXY_HOSTS に該当 + env セット → proxy 経由で fetch。"""
    monkeypatch.setenv(
        "SUPABASE_FETCH_JP_URL",
        "https://proj.supabase.co/functions/v1/fetch-jp",
    )
    monkeypatch.setenv("SUPABASE_FETCH_JP_KEY", "test-secret-key")

    httpx_mock.add_response(
        url="https://proj.supabase.co/functions/v1/fetch-jp?url=https%3A%2F%2Fwww.yodobashi.com%2Ftest",
        text="<html>proxied</html>",
    )

    result = await fetch_text("https://www.yodobashi.com/test")
    assert result == "<html>proxied</html>"

    req = httpx_mock.get_requests()[0]
    assert req.headers["x-proxy-key"] == "test-secret-key"
    # 実 URL は query param として送られる
    assert "url=https" in str(req.url)


@pytest.mark.asyncio
async def test_direct_fetch_for_non_proxy_host(httpx_mock, monkeypatch):
    """PROXY_HOSTS に該当しないホストは env セットされていても直接 fetch。"""
    monkeypatch.setenv(
        "SUPABASE_FETCH_JP_URL",
        "https://proj.supabase.co/functions/v1/fetch-jp",
    )
    monkeypatch.setenv("SUPABASE_FETCH_JP_KEY", "test-secret-key")

    # c-labo.jp は PROXY_HOSTS に含まれないので直接 fetch される
    httpx_mock.add_response(
        url="https://www.c-labo.jp/test",
        text="<html>direct</html>",
    )

    result = await fetch_text("https://www.c-labo.jp/test")
    assert result == "<html>direct</html>"

    req = httpx_mock.get_requests()[0]
    # proxy 経由ではない
    assert "x-proxy-key" not in req.headers
    assert "proj.supabase.co" not in str(req.url)


@pytest.mark.asyncio
async def test_direct_fetch_when_only_url_set_not_key(httpx_mock, monkeypatch):
    """URL のみ設定で KEY 未設定は直接 fetch にフォールバック (誤設定時の安全策)。"""
    monkeypatch.setenv(
        "SUPABASE_FETCH_JP_URL",
        "https://proj.supabase.co/functions/v1/fetch-jp",
    )
    monkeypatch.delenv("SUPABASE_FETCH_JP_KEY", raising=False)

    httpx_mock.add_response(
        url="https://www.yodobashi.com/test",
        text="<html>direct-fallback</html>",
    )

    result = await fetch_text("https://www.yodobashi.com/test")
    assert result == "<html>direct-fallback</html>"


def test_proxy_hosts_contains_disabled_adapters():
    """disabled adapter の host が PROXY_HOSTS に全て含まれていることを確認。"""
    # disabled adapter で US IP block が原因のもの
    assert "www.yodobashi.com" in PROXY_HOSTS
    assert "www.biccamera.com" in PROXY_HOSTS
    assert "www.amiami.com" in PROXY_HOSTS
    assert "www.amiami.jp" in PROXY_HOSTS
    assert "www.amazon.co.jp" in PROXY_HOSTS
