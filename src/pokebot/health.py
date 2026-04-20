from __future__ import annotations

import logging
from datetime import datetime, time, timedelta

from .notify.line import Notifier
from .storage.repo import EventRepo, SourceHealthRepo

log = logging.getLogger(__name__)

SILENCE_WARN_WINDOW = timedelta(hours=24)
NONZERO_LOOKBACK = timedelta(days=7)
FAILURE_ALERT_THRESHOLD = 5
WARN_DEBOUNCE = timedelta(hours=6)
DAILY_REPORT_WINDOW_MIN = 10  # 分: target 時刻から何分後までを発火窓とするか


def _summary_text(events_count: int, failing_sources: list[str]) -> str:
    lines = [
        "📊 ポケボット稼働中",
        f"直近24h: 検知 {events_count}件 / 失敗 {len(failing_sources)}ソース",
    ]
    if failing_sources:
        lines.append("▸ 失敗中: " + ", ".join(failing_sources))
    return "\n".join(lines)


class DailyReportJob:
    """毎日 JST `hhmm` の近辺で1回だけ発火する稼働レポート。

    DB の daily_reports テーブルで日付単位のロックを取り、重複発火を防ぐ。
    """

    def __init__(
        self,
        events: EventRepo,
        health: SourceHealthRepo,
        notifier: Notifier,
        hhmm: str = "09:00",
    ) -> None:
        self._events = events
        self._health = health
        self._notifier = notifier
        hour, minute = map(int, hhmm.split(":"))
        self._target = time(hour=hour, minute=minute)

    async def maybe_run(self, *, now: datetime) -> None:
        target_today = datetime.combine(now.date(), self._target)
        delta_min = (now - target_today).total_seconds() / 60
        if delta_min < 0 or delta_min >= DAILY_REPORT_WINDOW_MIN:
            return
        if not await self._claim_today(now.date()):
            return
        await self._run(now)

    async def _claim_today(self, today) -> bool:
        async with self._health.pool.acquire() as conn:
            status = await conn.execute(
                "INSERT INTO daily_reports (date) VALUES ($1) ON CONFLICT DO NOTHING",
                today,
            )
        return status.endswith(" 1")

    async def _run(self, now: datetime) -> None:
        since = now - timedelta(hours=24)
        async with self._events.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COUNT(*) AS c FROM events WHERE detected_at >= $1", since
            )
            failing_rows = await conn.fetch(
                "SELECT source FROM source_health WHERE consecutive_failures > 0"
            )
        count = row["c"]
        failing = [r["source"] for r in failing_rows]
        await self._notifier.send(_summary_text(count, failing))


class SilenceDetector:
    """パーサ無言検知 + 連続失敗警告。DB の source_health.last_warned_at で重複送信を抑止。"""

    def __init__(self, health: SourceHealthRepo, notifier: Notifier) -> None:
        self._health = health
        self._notifier = notifier

    async def tick(self, *, now: datetime) -> None:
        async with self._health.pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM source_health")
        for r in rows:
            source = r["source"]
            if self._should_warn_silence(r, now):
                await self._warn(source, now, f"🛑 パーサ要確認: {source}")
            if r["consecutive_failures"] >= FAILURE_ALERT_THRESHOLD:
                await self._warn(
                    source,
                    now,
                    f"🛑 ソース異常: {source} ({r['consecutive_failures']}連続失敗)",
                )

    def _should_warn_silence(self, r, now: datetime) -> bool:
        """過去7日以内に非ゼロ実績があり、直近24hは非ゼロなしの場合に警告。"""
        nonzero = r["last_nonzero_detection_at"]
        if not nonzero:
            return False
        age = now - nonzero
        return SILENCE_WARN_WINDOW < age <= NONZERO_LOOKBACK

    async def _warn(self, source: str, now: datetime, msg: str) -> None:
        rec = await self._health.get(source)
        if rec and rec.last_warned_at and (now - rec.last_warned_at) < WARN_DEBOUNCE:
            return
        await self._notifier.send(msg)
        await self._health.record_warning(source, now)
