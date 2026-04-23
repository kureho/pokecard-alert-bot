from __future__ import annotations

import logging

import httpx

log = logging.getLogger(__name__)

# Discord message content の上限は 2000 文字。LINE の 500 文字より十分広いが、
# 長文は読みづらいので LINE と同じ 500 文字カットで揃える。
_MAX_CONTENT_LENGTH = 500


class DiscordWebhookNotifier:
    """Discord Webhook 経由で通知を送る Notifier。

    LINE の sidecar として使う。LINE dedupe / quiet hours / cap をそのまま継承するので、
    LINE が送るものだけ Discord にも並行送信する (LINE が suppress するものは Discord も送らない)。

    Webhook URL の発行手順 (README 参照):
      1. Discord サーバー設定 → 連携サービス → ウェブフック
      2. 「新しいウェブフック」でチャネルを選択し URL コピー
      3. GitHub Actions の secrets に DISCORD_WEBHOOK_URL として登録
    """

    def __init__(self, webhook_url: str, *, timeout: float = 10.0) -> None:
        self._url = webhook_url
        self._timeout = timeout
        self.sent: list[str] = []

    async def send(self, text: str) -> None:
        content = text[:_MAX_CONTENT_LENGTH]
        self.sent.append(content)
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(self._url, json={"content": content})
            # 204 No Content が正常 (Discord の仕様)。200 も許容。
            if resp.status_code not in (200, 204):
                log.warning(
                    "discord webhook status=%s body=%s",
                    resp.status_code,
                    resp.text[:200],
                )
                resp.raise_for_status()
