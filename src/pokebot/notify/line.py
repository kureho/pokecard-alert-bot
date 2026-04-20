from __future__ import annotations

import logging
from typing import Protocol

from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    PushMessageRequest,
    TextMessage,
)

log = logging.getLogger(__name__)


class Notifier(Protocol):
    async def send(self, text: str) -> None: ...


class LineNotifier:
    def __init__(self, token: str, user_id: str) -> None:
        self._cfg = Configuration(access_token=token)
        self._user_id = user_id

    async def send(self, text: str) -> None:
        import asyncio

        await asyncio.to_thread(self._send_sync, text)

    def _send_sync(self, text: str) -> None:
        with ApiClient(self._cfg) as client:
            api = MessagingApi(client)
            api.push_message(
                PushMessageRequest(
                    to=self._user_id,
                    messages=[TextMessage(text=text)],
                )
            )


class DryRunNotifier:
    """DRY_RUN=1 で有効化。LINE に送らずログに出すだけ。"""

    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, text: str) -> None:
        self.sent.append(text)
        preview = text.replace("\n", " / ")[:120]
        log.info("[DRY_RUN] would-send (#%d): %s", len(self.sent), preview)
