from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from tenacity import AsyncRetrying, RetryError, stop_after_attempt, wait_exponential

from ..lib.confidence import CONFIDENCE_HIGH
from ..lib.dedupe import build_notification_dedupe_key
from ..notify.line import DryRunNotifier, Notifier
from ..storage.repos import (
    LotteryEvent,
    LotteryEventRepo,
    NotificationRepo,
    Product,
    ProductRepo,
)

log = logging.getLogger(__name__)

DEFAULT_MAX_PER_RUN = 2
# LINE 無料枠 200通/月 ≒ 6.7/日 の安全圏。月合計 180 まで許容。
DEFAULT_MAX_PER_DAY = 6
# 新鮮度: first_seen_at がこの期間内の event のみ通知対象。store_voice feed の過去履歴を除外する。
DEFAULT_FRESH_WINDOW = timedelta(days=3)

CONFIRMATION_LABEL = {
    "confirmed": "[高信頼]",
    "unconfirmed": "[未確認]",
    "conflicting": "[要確認]",
}

SALES_TYPE_LABEL = {
    "lottery": "抽選受付中",
    "preorder_lottery": "予約抽選",
    "invitation": "招待制販売",
    "first_come": "先着販売",
    "numbered_ticket": "整理券販売",
    "unknown": "販売方法未確定",
}

SOURCE_NOTE_BY_RETAILER = {
    "pokemoncenter_online": "ポケモンセンター公式",
    "pokemoncenter": "ポケモンセンター店舗",
    "yodobashi": "ヨドバシ公式",
    "biccamera": "ビックカメラ公式",
    "pokemon_official": "ポケモン公式",
}

# 通知対象の sales_type allowlist。unknown/空は送らない。
NOTIFY_SALES_TYPES = {
    "lottery",
    "preorder_lottery",
    "first_come",
    "numbered_ticket",
    "invitation",
}


def _format_dt(dt: datetime | None) -> str:
    if dt is None:
        return "未定"
    # `%-m` は POSIX 拡張で Windows 非対応のため、手動フォーマットにして移植性を担保
    return f"{dt.month}/{dt.day} {dt.hour:02d}:{dt.minute:02d}"


def format_event_message(
    event: LotteryEvent, *, product: Product | None = None, source_note: str = ""
) -> str:
    label = CONFIRMATION_LABEL.get(event.official_confirmation_status, "[不明]")
    stype = SALES_TYPE_LABEL.get(event.sales_type, event.sales_type)
    product_name = product.canonical_name if product else event.canonical_title
    location = event.retailer_name
    if event.store_name:
        location = f"{event.retailer_name} / {event.store_name}"
    lines = [
        f"{label} {product_name}",
        f"{location}",
        f"種別: {stype}",
    ]
    if event.apply_start_at or event.apply_end_at:
        lines.append(f"応募: {_format_dt(event.apply_start_at)}〜{_format_dt(event.apply_end_at)}")
    if event.result_at:
        lines.append(f"結果: {_format_dt(event.result_at)}")
    if event.purchase_end_at:
        lines.append(f"購入期限: {_format_dt(event.purchase_end_at)}")
    if event.purchase_limit_text:
        lines.append(f"条件: {event.purchase_limit_text}")
    if event.conditions_text and event.conditions_text != event.purchase_limit_text:
        lines.append(f"備考: {event.conditions_text}")
    if source_note:
        lines.append(f"情報源: {source_note}")
    if event.source_primary_url:
        lines.append(event.source_primary_url)
    return "\n".join(lines)


@dataclass
class NotificationResult:
    new_sent: int = 0
    update_sent: int = 0
    suppressed: int = 0
    skipped_low_confidence: int = 0


class NotificationDispatcher:
    """lottery_events を走査し、new/update 通知を LINE に送る。

    - dedupe: notifications テーブルで二重送信防止
    - cap: per-run / per-day 上限
    - フィルタ: confidence_score >= CONFIDENCE_HIGH AND confirmation_status='confirmed' のみ通知
    """

    def __init__(
        self,
        *,
        lottery_repo: LotteryEventRepo,
        product_repo: ProductRepo,
        notification_repo: NotificationRepo,
        notifier: Notifier,
        max_per_run: int = DEFAULT_MAX_PER_RUN,
        max_per_day: int = DEFAULT_MAX_PER_DAY,
        fresh_window: timedelta = DEFAULT_FRESH_WINDOW,
    ) -> None:
        self._lottery = lottery_repo
        self._product = product_repo
        self._notif = notification_repo
        self._notifier = notifier
        self._max_per_run = max_per_run
        self._max_per_day = max_per_day
        self._fresh_window = fresh_window

    async def dispatch_for_event(
        self,
        event: LotteryEvent,
        *,
        notification_type: str,
        now: datetime,
        result: NotificationResult,
    ) -> None:
        """1イベントにつき 1 通知を試行。new or update どちらかの1本。"""
        if event.sales_type not in NOTIFY_SALES_TYPES:
            result.skipped_low_confidence += 1
            return
        if event.confidence_score < CONFIDENCE_HIGH:
            result.skipped_low_confidence += 1
            return
        if event.official_confirmation_status != "confirmed":
            result.skipped_low_confidence += 1
            return

        # dedupe key: new は1度だけ送る。update は last_seen_at の分単位 ISO で差別化し、
        # 情報量増加のたびに 1 本だけ送れるようにする。
        if notification_type == "update":
            content_version = event.last_seen_at.isoformat(timespec="minutes")
        else:
            content_version = "v1"
        ndk = build_notification_dedupe_key(
            lottery_dedupe_key=event.dedupe_key,
            notification_type=notification_type,
            content_version=content_version,
        )

        product = None
        if event.product_id:
            # Repo にシンプルな find_by_id は無いので list_all から探す（Phase 1 は少数想定）
            products = await self._product.list_all(limit=1000)
            for p in products:
                if p.id == event.product_id:
                    product = p
                    break

        source_note = SOURCE_NOTE_BY_RETAILER.get(event.retailer_name, event.retailer_name)
        summary = format_event_message(event, product=product, source_note=source_note)

        # DRY_RUN: notifications テーブルに触れず、would-send ログのみ出す。
        # これにより本番 run 時に過去の DRY_RUN 予約が suppress 原因にならない。
        if isinstance(self._notifier, DryRunNotifier):
            try:
                await self._notifier.send(summary)
                if notification_type == "new":
                    result.new_sent += 1
                elif notification_type == "update":
                    result.update_sent += 1
            except Exception as e:  # noqa: BLE001
                log.warning("dry_run send failed for event %s: %s", event.id, e)
            return

        claim_id = await self._notif.try_claim(
            lottery_event_id=event.id,
            notification_type=notification_type,
            channel="line",
            dedupe_key=ndk,
            payload_summary=summary[:500],
        )
        if claim_id is None:
            result.suppressed += 1
            return

        # 実送信
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(3),
                wait=wait_exponential(multiplier=1, min=1, max=30),
                reraise=True,
            ):
                with attempt:
                    await self._notifier.send(summary)
        except RetryError:
            log.warning("notification retry exhausted for event %s", event.id)
            return
        except Exception as e:  # noqa: BLE001
            log.warning("notification send failed for event %s: %s", event.id, e)
            return

        await self._notif.mark_sent(claim_id, now)
        if notification_type == "new":
            result.new_sent += 1
        elif notification_type == "update":
            result.update_sent += 1

    async def _count_sent_today(self, now: datetime) -> int:
        """per-day cap カウント。seed/silence/daily_summary 等 LINE 内部管理用通知は除外。

        実際にユーザーの LINE に届く new/update/deadline/result のみをカウントする。
        """
        if self._max_per_day is None:
            return 0
        async with self._lottery.pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT COUNT(*) AS c FROM notifications
                   WHERE sent_at IS NOT NULL AND sent_at >= $1
                     AND notification_type IN ('new', 'update', 'deadline', 'result')""",
                now.replace(hour=0, minute=0, second=0, microsecond=0),
            )
        return row["c"] if row else 0

    async def dispatch(self, *, now: datetime) -> NotificationResult:
        """active な lottery_events を処理。新規 (new 未送) を優先的に送る。

        Phase 1 は update 通知を明示的に発火するためのフックは後続実装。
        この関数は "未送信 new" を new として処理する。
        """
        result = NotificationResult()
        since = now - self._fresh_window
        events = await self._lottery.list_active_since(since, limit=200)
        log.info(
            "dispatch: now=%s since=%s candidate_events=%d", now, since, len(events)
        )

        per_day_used = await self._count_sent_today(now)
        log.info("dispatch: per_day_used=%d max_per_day=%s", per_day_used, self._max_per_day)

        sent_this_run = 0
        for ev in events:
            if self._max_per_run is not None and sent_this_run >= self._max_per_run:
                log.warning("notify per-run cap %d reached", self._max_per_run)
                break
            if (
                self._max_per_day is not None
                and (per_day_used + sent_this_run) >= self._max_per_day
            ):
                log.warning(
                    "notify per-day cap %d reached (today=%d)",
                    self._max_per_day,
                    per_day_used,
                )
                break
            before_new = result.new_sent
            await self.dispatch_for_event(
                ev,
                notification_type="new",
                now=now,
                result=result,
            )
            if result.new_sent > before_new:
                sent_this_run += 1
        return result

    async def dispatch_updates(self, *, now: datetime) -> NotificationResult:
        """直近 updated された active event で、既に new 通知送信済みのものに対し
        update 通知を送る。dedupe_key は last_seen_at 分単位で差別化。

        - 対象: updated_at >= now - fresh_window の active event
        - 前提: 同 event の new 通知が sent 済み (そうでなければ update を先行発火しない)
        - cap: per-run / per-day は new と共有 (同じ notifications テーブル)
        """
        result = NotificationResult()
        since = now - self._fresh_window
        events = await self._lottery.list_recently_updated_since(since, limit=200)

        per_day_used = await self._count_sent_today(now)

        sent_this_run = 0
        for ev in events:
            if self._max_per_run is not None and sent_this_run >= self._max_per_run:
                log.warning("notify_updates per-run cap %d reached", self._max_per_run)
                break
            if (
                self._max_per_day is not None
                and (per_day_used + sent_this_run) >= self._max_per_day
            ):
                log.warning(
                    "notify_updates per-day cap %d reached (today=%d)",
                    self._max_per_day,
                    per_day_used,
                )
                break
            # new 通知が既に送信済みの event だけが update 対象
            if not await self._notif.has_notification_sent(
                lottery_event_id=ev.id, notification_type="new"
            ):
                continue
            before = result.update_sent
            await self.dispatch_for_event(
                ev, notification_type="update", now=now, result=result,
            )
            if result.update_sent > before:
                sent_this_run += 1
        return result
