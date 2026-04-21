from datetime import datetime, timedelta

import pytest

from pokebot.services.daily_summary import (
    DailySummaryService,
    SummarySnapshot,
    format_summary,
)
from pokebot.storage.repos import NotificationRepo


class FakeNotifier:
    def __init__(self):
        self.sent = []

    async def send(self, text):
        self.sent.append(text)


def test_format_summary_all_good():
    s = SummarySnapshot(
        active_count=3,
        notifications_today=1,
        pending_review_count=5,
        archived_count=100,
        failing_sources=[],
        new_active_last_24h=2,
    )
    msg = format_summary(s)
    assert "active: 3" in msg
    assert "全ソース正常" in msg
    assert "直近24h新規 2" in msg


def test_format_summary_with_failures():
    s = SummarySnapshot(
        active_count=0,
        notifications_today=0,
        pending_review_count=0,
        archived_count=0,
        failing_sources=["yodobashi_lottery", "amiami_lottery"],
        new_active_last_24h=0,
    )
    msg = format_summary(s)
    assert "yodobashi_lottery" in msg
    assert "amiami_lottery" in msg
    assert "失敗中" in msg


@pytest.mark.asyncio
async def test_fires_in_target_window(db):
    notifier = FakeNotifier()
    svc = DailySummaryService(
        db=db,
        notification_repo=NotificationRepo(db),
        notifier=notifier,
        hhmm="09:00",
    )
    now = datetime(2026, 4, 21, 9, 10)  # 窓内
    fired = await svc.maybe_run(now=now)
    assert fired is True
    assert len(notifier.sent) == 1
    assert "日次サマリ" in notifier.sent[0]


@pytest.mark.asyncio
async def test_does_not_fire_outside_window(db):
    notifier = FakeNotifier()
    svc = DailySummaryService(
        db=db,
        notification_repo=NotificationRepo(db),
        notifier=notifier,
        hhmm="09:00",
    )
    now = datetime(2026, 4, 21, 15, 0)  # 窓外
    fired = await svc.maybe_run(now=now)
    assert fired is False
    assert notifier.sent == []


@pytest.mark.asyncio
async def test_does_not_fire_before_window(db):
    notifier = FakeNotifier()
    svc = DailySummaryService(
        db=db,
        notification_repo=NotificationRepo(db),
        notifier=notifier,
        hhmm="09:00",
    )
    # 08:59 は target より前
    now = datetime(2026, 4, 21, 8, 59)
    fired = await svc.maybe_run(now=now)
    assert fired is False


@pytest.mark.asyncio
async def test_does_not_double_fire(db):
    notifier = FakeNotifier()
    svc = DailySummaryService(
        db=db,
        notification_repo=NotificationRepo(db),
        notifier=notifier,
        hhmm="09:00",
    )
    now = datetime(2026, 4, 21, 9, 10)
    await svc.maybe_run(now=now)
    # 同じ日に再呼び出し (5分後、まだ窓内)
    await svc.maybe_run(now=now + timedelta(minutes=5))
    assert len(notifier.sent) == 1
