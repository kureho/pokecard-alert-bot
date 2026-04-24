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
from ..lib.quiet_hours import is_quiet_hours
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


@dataclass
class DigestEntry:
    """Daily digest の 1 行: 未確認だが注視すべき候補。"""

    title: str
    retailer: str
    sales_type: str
    cross_sources: int  # 同じ product を検出している source 数
    confidence_level: str | None = None  # Tier 分離用 (confirmed_medium / candidate)


@dataclass
class DeadlineSoonEntry:
    """apply_end_at が 24h 以内の active event (event-centric 設計で deadline 個別通知を
    廃止したため、daily_summary で代替リマインドする)。"""

    title: str
    retailer: str
    store_name: str | None
    apply_end_at: datetime


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


async def _collect_unconfirmed_digest(
    db: Database, now: datetime, *, limit: int = 12
) -> list[DigestEntry]:
    """直近24h の active event のうち confirmed_strong 未満の候補を列挙する。

    confirmed_strong は即時 LINE 通知済みなので digest からは除外。
    confirmed_medium (Tier B) を優先的に列挙し、candidate は補助的に。

    format_summary 側で Tier B / candidate にセクション分割して表示する。
    """
    since_24h = now - timedelta(hours=24)
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT le.canonical_title, le.retailer_name,
                      le.sales_type, le.product_name_normalized,
                      le.confidence_score, le.official_confirmation_status,
                      le.confidence_level,
                      (
                        SELECT COUNT(DISTINCT les.source_id)
                          FROM lottery_event_sources les
                          JOIN lottery_events le2 ON le2.id = les.lottery_event_id
                         WHERE le2.product_name_normalized = le.product_name_normalized
                      ) AS cross_sources
               FROM lottery_events le
               WHERE le.status = 'active'
                 AND le.first_seen_at >= $1
                 AND (
                       le.confidence_level IN ('confirmed_medium', 'candidate')
                       OR (
                         le.confidence_level IS NULL
                         AND (le.official_confirmation_status != 'confirmed'
                              OR le.confidence_score < 90)
                       )
                     )
               ORDER BY
                   CASE le.confidence_level
                     WHEN 'confirmed_medium' THEN 0
                     WHEN 'candidate' THEN 1
                     ELSE 2
                   END,
                   le.first_seen_at DESC
               LIMIT $2""",
            since_24h, limit,
        )
    return [
        DigestEntry(
            title=(r["canonical_title"] or "")[:60],
            retailer=r["retailer_name"] or "-",
            sales_type=r["sales_type"] or "unknown",
            cross_sources=r["cross_sources"] or 0,
            confidence_level=r["confidence_level"],
        )
        for r in rows
    ]


def _fmt_short_dt(dt: datetime) -> str:
    """M/D HH:MM の短縮表示。"""
    return f"{dt.month}/{dt.day} {dt.hour:02d}:{dt.minute:02d}"


def format_summary(
    snapshot: SummarySnapshot,
    digest: list[DigestEntry] | None = None,
    deadline_soon: list[DeadlineSoonEntry] | None = None,
    *,
    tier_b_limit: int = 5,
    candidate_limit: int = 3,
    deadline_limit: int = 8,
) -> str:
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

    # ⏰ 締切前: event-centric 設計で個別 deadline 通知を廃止した代替リマインド。
    # 応募期限が近い active event を期限順でまとめて通知する。
    if deadline_soon:
        lines.append("")
        lines.append(f"⏰ 締切24h以内 ({len(deadline_soon)}件):")
        for d in deadline_soon[:deadline_limit]:
            loc = d.retailer
            if d.store_name:
                loc = f"{d.retailer}/{d.store_name}"
            lines.append(
                f"  {_fmt_short_dt(d.apply_end_at)} {loc[:20]}: {d.title[:40]}"
            )

    if digest:
        # Tier 分離: confirmed_medium を優先して列挙、候補(candidate / legacy)は別枠
        tier_b = [d for d in digest if d.confidence_level == "confirmed_medium"]
        others = [d for d in digest if d.confidence_level != "confirmed_medium"]
        if tier_b:
            lines.append("")
            lines.append(f"▸ 要注視 Tier B ({len(tier_b)}件):")
            for d in tier_b[:tier_b_limit]:
                badge = f"[{d.cross_sources}src] " if d.cross_sources >= 2 else ""
                lines.append(f"  {badge}{d.sales_type}: {d.title}")
        if others:
            lines.append("")
            lines.append(f"▸ 候補 ({len(others)}件):")
            for d in others[:candidate_limit]:
                badge = f"[{d.cross_sources}src] " if d.cross_sources >= 2 else ""
                lines.append(f"  {badge}{d.sales_type}: {d.title}")
    return "\n".join(lines)


async def _collect_deadline_soon(
    db: Database, now: datetime, *, within_hours: int = 24, limit: int = 15
) -> list[DeadlineSoonEntry]:
    """apply_end_at が now から within_hours 以内の active event を期限順で列挙。

    event-centric 設計 (Plan B 2026-04-24) で個別 deadline 通知を廃止したため、
    代替として daily_summary でまとめてリマインドする。
    """
    cutoff = now + timedelta(hours=within_hours)
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT canonical_title, retailer_name, store_name, apply_end_at
               FROM lottery_events
               WHERE status = 'active'
                 AND apply_end_at IS NOT NULL
                 AND apply_end_at >= $1
                 AND apply_end_at <= $2
               ORDER BY apply_end_at ASC
               LIMIT $3""",
            now, cutoff, limit,
        )
    return [
        DeadlineSoonEntry(
            title=(r["canonical_title"] or "")[:60],
            retailer=r["retailer_name"] or "-",
            store_name=r["store_name"],
            apply_end_at=r["apply_end_at"],
        )
        for r in rows
    ]


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
        # 夜間通知抑止の対象。target を quiet hours 内に設定しても送られない
        # (デフォルト target=10:00 は抑止窓の外)。
        if is_quiet_hours(now):
            return False
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
        digest = await _collect_unconfirmed_digest(self._db, now)
        deadline_soon = await _collect_deadline_soon(self._db, now)
        msg = format_summary(snapshot, digest=digest, deadline_soon=deadline_soon)

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
