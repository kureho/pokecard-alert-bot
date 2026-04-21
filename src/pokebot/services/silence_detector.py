"""Source の連続失敗/長時間無反応を検知して LINE で警告するサービス。

- 連続失敗 >= FAILURE_ALERT_THRESHOLD: 即警告
- last_success_at が SILENCE_WARNING_HOURS より古く、かつ直近 1h に attempt がある場合: 警告
- 同一 source×理由 に対し WARN_DEBOUNCE_HOURS 以内の送信履歴があれば skip
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from ..lib.dedupe import build_notification_dedupe_key
from ..lib.quiet_hours import is_quiet_hours
from ..notify.line import Notifier
from ..storage.db import Database
from ..storage.repos import NotificationRepo

log = logging.getLogger(__name__)

FAILURE_ALERT_THRESHOLD = 5  # 連続失敗回数
SILENCE_WARNING_HOURS = 48  # 最終成功からの閾値
WARN_DEBOUNCE_HOURS = 24  # 同一ソース警告の debounce


@dataclass
class SilenceWarning:
    source_name: str
    reason: str  # "consecutive_failures" or "long_silence"
    detail: str


async def _collect_warnings(db: Database, now: datetime) -> list[SilenceWarning]:
    warnings: list[SilenceWarning] = []
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT source_name, consecutive_failures, last_success_at,
                      last_attempt_at, last_error
               FROM sources WHERE is_active = TRUE"""
        )
    for r in rows:
        source = r["source_name"]
        fails = r["consecutive_failures"]
        last_success = r["last_success_at"]
        last_attempt = r["last_attempt_at"]
        err = (r["last_error"] or "")[:60]
        if fails >= FAILURE_ALERT_THRESHOLD:
            warnings.append(
                SilenceWarning(
                    source_name=source,
                    reason="consecutive_failures",
                    detail=f"{fails}回連続失敗 / {err}",
                )
            )
        elif last_success and last_attempt:
            age = now - last_success
            if age > timedelta(hours=SILENCE_WARNING_HOURS) and (now - last_attempt) < timedelta(
                hours=1
            ):
                warnings.append(
                    SilenceWarning(
                        source_name=source,
                        reason="long_silence",
                        detail=f"最終成功 {age.total_seconds() / 3600:.1f}h 前",
                    )
                )
    return warnings


class SilenceDetector:
    def __init__(
        self,
        *,
        db: Database,
        notification_repo: NotificationRepo,
        notifier: Notifier,
    ) -> None:
        self._db = db
        self._notif = notification_repo
        self._notifier = notifier

    async def tick(self, *, now: datetime) -> int:
        """各失敗ソースに対し、24h 間隔以上空いていれば LINE で警告。送信件数を返す。"""
        if is_quiet_hours(now):
            # 夜間の監視アラートも抑止。次回 tick で debounce が残っていれば送らない。
            log.info("silence tick: quiet hours (%s), skip", now.strftime("%H:%M"))
            return 0
        warnings = await _collect_warnings(self._db, now)
        sent = 0
        for w in warnings:
            # debounce: 同一 source×理由 に対し 24h 内の send 履歴があれば skip。
            # dedupe_key は `silence|{source}|{reason}#silence#{YYYYMMDDHH}` 形式
            # (build_notification_dedupe_key が # で連結)。前方一致で比較する。
            async with self._db.pool.acquire() as conn:
                recent = await conn.fetchval(
                    """SELECT COUNT(*) FROM notifications
                       WHERE notification_type = $1 AND dedupe_key LIKE $2
                         AND sent_at IS NOT NULL
                         AND sent_at >= $3""",
                    "silence",
                    f"silence|{w.source_name}|{w.reason}#%",
                    now - timedelta(hours=WARN_DEBOUNCE_HOURS),
                )
            if recent:
                continue
            # 今回の claim_key (時間単位で一意化)
            ndk = build_notification_dedupe_key(
                lottery_dedupe_key=f"silence|{w.source_name}|{w.reason}",
                notification_type="silence",
                content_version=now.strftime("%Y%m%d%H"),
            )
            msg = f"⚠️ 監視ソース異常: {w.source_name}\n理由: {w.reason}\n{w.detail}"
            try:
                await self._notifier.send(msg)
            except Exception as e:  # noqa: BLE001
                log.warning("silence notify send failed: %s", e)
                continue
            async with self._db.pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO notifications
                         (lottery_event_id, notification_type, channel, dedupe_key,
                          payload_summary, sent_at)
                       VALUES (NULL, 'silence', 'line', $1, $2, $3)
                       ON CONFLICT (dedupe_key) DO NOTHING""",
                    ndk,
                    msg[:500],
                    now,
                )
            sent += 1
        return sent
