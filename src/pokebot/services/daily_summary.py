"""日次稼働サマリを LINE で送るサービス。

JST 09:00 〜 09:30 の窓内で 1日1回だけ発火 (notifications テーブルの
notification_type='daily_summary' 同日レコードで claim)。
- 直近24hの active 件数 / 通知件数 / pending_review 件数
- 失敗継続ソース一覧
- 何も起きない日でも LINE に「稼働中」シグナルとして届く
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from ..lib.dedupe import build_notification_dedupe_key
from ..notify.line import Notifier
from ..storage.db import Database
from ..storage.repos import NotificationRepo

log = logging.getLogger(__name__)

# 発火窓: target (例: 09:00) から何分後までを発火可能とするか
DAILY_REPORT_WINDOW_MIN = 30


@dataclass
class SummarySnapshot:
    active_count: int
    notifications_today: int
    pending_review_count: int
    archived_count: int
    failing_sources: list[str]
    new_active_last_24h: int


async def _collect(db: Database, now: datetime) -> SummarySnapshot:
    since_24h = now - timedelta(hours=24)
    async with db.pool.acquire() as conn:
        active = await conn.fetchval("SELECT COUNT(*) FROM lottery_events WHERE status = 'active'")
        pending = await conn.fetchval(
            "SELECT COUNT(*) FROM lottery_events WHERE status = 'pending_review'"
        )
        archived = await conn.fetchval(
            "SELECT COUNT(*) FROM lottery_events WHERE status = 'archived'"
        )
        new_24h = await conn.fetchval(
            "SELECT COUNT(*) FROM lottery_events WHERE first_seen_at >= $1",
            since_24h,
        )
        sent_today = await conn.fetchval(
            """SELECT COUNT(*) FROM notifications
               WHERE sent_at IS NOT NULL AND sent_at >= $1""",
            now.replace(hour=0, minute=0, second=0, microsecond=0),
        )
        failing_rows = await conn.fetch(
            """SELECT source_name FROM sources
               WHERE consecutive_failures >= 3 AND is_active = TRUE
               ORDER BY consecutive_failures DESC"""
        )
    return SummarySnapshot(
        active_count=active or 0,
        notifications_today=sent_today or 0,
        pending_review_count=pending or 0,
        archived_count=archived or 0,
        failing_sources=[r["source_name"] for r in failing_rows],
        new_active_last_24h=new_24h or 0,
    )


def format_summary(snapshot: SummarySnapshot) -> str:
    lines = [
        "📊 ポケボット日次サマリ",
        f"active: {snapshot.active_count} 件 (直近24h新規 {snapshot.new_active_last_24h})",
        f"今日の通知: {snapshot.notifications_today} 件",
        f"保留(unknown): {snapshot.pending_review_count} / archive: {snapshot.archived_count}",
    ]
    if snapshot.failing_sources:
        lines.append("▸ 失敗中 (3回以上): " + ", ".join(snapshot.failing_sources))
    else:
        lines.append("▸ 全ソース正常")
    return "\n".join(lines)


class DailySummaryService:
    """1日1回、JST 09:00 窓で稼働サマリを LINE 送信。

    notifications テーブルに dedupe_key で claim することで重複発火を防ぐ。
    lottery_event_id は NULL 許可スキーマ (2026-04-21 migration)。
    """

    def __init__(
        self,
        *,
        db: Database,
        notification_repo: NotificationRepo,
        notifier: Notifier,
        hhmm: str = "09:00",
    ) -> None:
        self._db = db
        self._notif = notification_repo
        self._notifier = notifier
        hour, minute = map(int, hhmm.split(":"))
        self._target = time(hour=hour, minute=minute)

    async def maybe_run(self, *, now: datetime) -> bool:
        """発火窓内で未送信なら送信。送信したら True。"""
        target_today = datetime.combine(now.date(), self._target)
        delta_min = (now - target_today).total_seconds() / 60
        if delta_min < 0 or delta_min >= DAILY_REPORT_WINDOW_MIN:
            return False

        # 今日分を claim (同日内の重複発火防止)
        claim_key = f"daily_summary|{now.date().isoformat()}"
        ndk = build_notification_dedupe_key(
            lottery_dedupe_key=claim_key,
            notification_type="daily_summary",
            content_version="v1",
        )
        # dedupe_key 一致の sent レコードがすでにあれば skip
        async with self._db.pool.acquire() as conn:
            existing = await conn.fetchval(
                """SELECT sent_at FROM notifications
                   WHERE dedupe_key = $1""",
                ndk,
            )
        if existing is not None:
            return False

        snapshot = await _collect(self._db, now)
        msg = format_summary(snapshot)

        # claim: INSERT ON CONFLICT DO NOTHING. 衝突したら他プロセスが既に処理中。
        async with self._db.pool.acquire() as conn:
            claim = await conn.fetchrow(
                """INSERT INTO notifications
                     (lottery_event_id, notification_type, channel, dedupe_key,
                      payload_summary)
                   VALUES (NULL, 'daily_summary', 'line', $1, $2)
                   ON CONFLICT (dedupe_key) DO NOTHING
                   RETURNING id""",
                ndk,
                msg[:500],
            )
        if claim is None:
            return False

        try:
            await self._notifier.send(msg)
        except Exception as e:  # noqa: BLE001
            log.warning("daily summary send failed: %s", e)
            return False

        async with self._db.pool.acquire() as conn:
            await conn.execute(
                "UPDATE notifications SET sent_at = $1 WHERE id = $2",
                now,
                claim["id"],
            )
        return True
