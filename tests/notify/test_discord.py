"""DiscordWebhookNotifier の HTTP 挙動検証 (pytest-httpx でモック)。"""

from __future__ import annotations

import httpx
import pytest

from pokebot.notify.discord import DiscordWebhookNotifier


WEBHOOK = "https://discord.com/api/webhooks/123/abc"


@pytest.mark.asyncio
async def test_sends_content_as_json(httpx_mock):
    httpx_mock.add_response(url=WEBHOOK, status_code=204)

    notifier = DiscordWebhookNotifier(webhook_url=WEBHOOK)
    await notifier.send("アビスアイ抽選受付中\nhttps://example.com/1")

    req = httpx_mock.get_requests()[0]
    assert req.method == "POST"
    assert req.url == WEBHOOK
    # body は JSON で content フィールドに text が入る
    import json
    body = json.loads(req.content)
    assert "アビスアイ" in body["content"]
    # notifier 内の送信履歴にも残る
    assert len(notifier.sent) == 1


@pytest.mark.asyncio
async def test_truncates_long_text(httpx_mock):
    """500文字を超えるメッセージは切り詰められる。"""
    httpx_mock.add_response(url=WEBHOOK, status_code=204)

    notifier = DiscordWebhookNotifier(webhook_url=WEBHOOK)
    await notifier.send("A" * 1000)

    import json
    body = json.loads(httpx_mock.get_requests()[0].content)
    assert len(body["content"]) == 500


@pytest.mark.asyncio
async def test_accepts_200_and_204(httpx_mock):
    """Discord は通常 204 No Content を返すが 200 も許容。"""
    httpx_mock.add_response(url=WEBHOOK, status_code=200)
    notifier = DiscordWebhookNotifier(webhook_url=WEBHOOK)
    await notifier.send("ok")


@pytest.mark.asyncio
async def test_raises_on_failure(httpx_mock):
    """4xx/5xx は raise_for_status で例外を飛ばす (caller が suppress する想定)。"""
    httpx_mock.add_response(url=WEBHOOK, status_code=500, text="oops")
    notifier = DiscordWebhookNotifier(webhook_url=WEBHOOK)
    with pytest.raises(httpx.HTTPStatusError):
        await notifier.send("ng")
