from datetime import datetime, timedelta

import pytest

from pokebot.services.daily_summary import (
    DailySummaryService,
    DeadlineSoonEntry,
    DigestEntry,
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
        hhmm="12:00",
    )
    now = datetime(2026, 4, 21, 12, 10)  # 窓内
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
        hhmm="12:00",
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
        hhmm="12:00",
    )
    # 11:59 は target より前
    now = datetime(2026, 4, 21, 11, 59)
    fired = await svc.maybe_run(now=now)
    assert fired is False


def test_format_summary_with_digest_splits_tier_b_and_candidates():
    s = SummarySnapshot(
        active_count=5,
        notifications_today=2,
        pending_review_count=1,
        archived_count=10,
        failing_sources=[],
        new_active_last_24h=3,
    )
    digest = [
        DigestEntry(
            title="アビスアイ招待リクエスト",
            retailer="amazon",
            sales_type="invitation",
            cross_sources=2,
            confidence_level="confirmed_medium",
        ),
        DigestEntry(
            title="メガリザードン抽選",
            retailer="pokemoncenter",
            sales_type="lottery",
            cross_sources=1,
            confidence_level="candidate",
        ),
    ]
    msg = format_summary(s, digest=digest)
    # Tier B セクションが出る
    assert "要注視 Tier B (1件)" in msg
    assert "アビスアイ招待リクエスト" in msg
    # 候補セクションは candidate だけ
    assert "候補 (1件)" in msg
    assert "メガリザードン抽選" in msg
    # cross_sources>=2 なら [2src] バッジ
    assert "[2src]" in msg


def test_format_summary_tier_b_only_no_candidate_section():
    s = SummarySnapshot(
        active_count=1,
        notifications_today=0,
        pending_review_count=0,
        archived_count=0,
        failing_sources=[],
        new_active_last_24h=1,
    )
    digest = [
        DigestEntry(
            title="メガドリームex",
            retailer="hobby_station",
            sales_type="lottery",
            cross_sources=3,
            confidence_level="confirmed_medium",
        ),
    ]
    msg = format_summary(s, digest=digest)
    assert "要注視 Tier B (1件)" in msg
    assert "候補 (" not in msg


def test_format_summary_legacy_digest_without_confidence_level():
    """confidence_level 未設定の legacy digest entry は 候補セクションに表示。"""
    s = SummarySnapshot(
        active_count=1,
        notifications_today=0,
        pending_review_count=0,
        archived_count=0,
        failing_sources=[],
        new_active_last_24h=1,
    )
    digest = [
        DigestEntry(
            title="古いイベント",
            retailer="misc",
            sales_type="unknown",
            cross_sources=1,
        ),
    ]
    msg = format_summary(s, digest=digest)
    assert "要注視 Tier B" not in msg
    assert "候補 (1件)" in msg
    assert "古いイベント" in msg


def test_format_summary_without_digest_no_section():
    s = SummarySnapshot(
        active_count=0,
        notifications_today=0,
        pending_review_count=0,
        archived_count=0,
        failing_sources=[],
        new_active_last_24h=0,
    )
    msg = format_summary(s, digest=None)
    assert "要注視 Tier B" not in msg
    assert "候補 (" not in msg
    # 空リストも同様
    msg2 = format_summary(s, digest=[])
    assert "要注視 Tier B" not in msg2
    assert "候補 (" not in msg2


@pytest.mark.asyncio
async def test_does_not_fire_during_quiet_hours(db):
    """target が quiet hours (21-10時) の中でも fire しない。

    既定 target=10:00 にして、now を quiet hours 内 (09:30) にしても
    maybe_run は False を返す。
    """
    notifier = FakeNotifier()
    svc = DailySummaryService(
        db=db,
        notification_repo=NotificationRepo(db),
        notifier=notifier,
        hhmm="09:30",  # 古い設定との互換を想定し、抑止帯内の target でも安全に止まる
    )
    now = datetime(2026, 4, 21, 9, 40)  # target 後 10 分 = 窓内だが quiet hours
    fired = await svc.maybe_run(now=now)
    assert fired is False
    assert notifier.sent == []


@pytest.mark.asyncio
async def test_does_not_double_fire(db):
    notifier = FakeNotifier()
    svc = DailySummaryService(
        db=db,
        notification_repo=NotificationRepo(db),
        notifier=notifier,
        hhmm="12:00",
    )
    now = datetime(2026, 4, 21, 12, 10)
    await svc.maybe_run(now=now)
    # 同じ日に再呼び出し (5分後、まだ窓内)
    await svc.maybe_run(now=now + timedelta(minutes=5))
    assert len(notifier.sent) == 1


# ===== deadline_soon セクション (event-centric 設計の deadline 個別通知廃止の代替) =====


def test_format_summary_includes_deadline_section():
    """deadline_soon が渡されると ⏰ セクションが表示される。"""
    s = SummarySnapshot(
        active_count=5,
        notifications_today=1,
        pending_review_count=0,
        archived_count=0,
        failing_sources=[],
        new_active_last_24h=3,
    )
    deadline = [
        DeadlineSoonEntry(
            title="アビスアイ / エディオン",
            retailer="edion",
            store_name="エディオン",
            apply_end_at=datetime(2026, 4, 24, 23, 59),
        ),
        DeadlineSoonEntry(
            title="アビスアイ / TSUTAYA",
            retailer="tsutaya",
            store_name="TSUTAYA流山",
            apply_end_at=datetime(2026, 4, 25, 10, 0),
        ),
    ]
    text = format_summary(s, deadline_soon=deadline)
    assert "⏰" in text
    assert "締切24h以内" in text
    assert "エディオン" in text
    assert "4/24 23:59" in text


def test_format_summary_no_deadline_section_when_empty():
    """deadline_soon=None または空なら ⏰ セクション出さない。"""
    s = SummarySnapshot(
        active_count=5,
        notifications_today=1,
        pending_review_count=0,
        archived_count=0,
        failing_sources=[],
        new_active_last_24h=3,
    )
    # deadline_soon 渡さない
    text1 = format_summary(s)
    assert "⏰" not in text1
    # 空 list
    text2 = format_summary(s, deadline_soon=[])
    assert "⏰" not in text2


def test_format_summary_deadline_limit_respected():
    """deadline_limit で表示上限が効く。"""
    s = SummarySnapshot(
        active_count=20,
        notifications_today=0,
        pending_review_count=0,
        archived_count=0,
        failing_sources=[],
        new_active_last_24h=20,
    )
    deadline = [
        DeadlineSoonEntry(
            title=f"商品{i}",
            retailer="x",
            store_name=f"store{i}",
            apply_end_at=datetime(2026, 4, 24, 23, 59),
        )
        for i in range(15)
    ]
    text = format_summary(s, deadline_soon=deadline, deadline_limit=3)
    # header に全件数は出るが、明細は 3 件だけ
    assert "締切24h以内 (15件)" in text
    count = sum(1 for line in text.split("\n") if "store" in line)
    assert count == 3
