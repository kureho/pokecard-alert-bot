from datetime import datetime, timedelta

import pytest

from pokebot.services.silence_detector import SilenceDetector
from pokebot.storage.repos import NotificationRepo, SourceRepo


class FakeNotifier:
    def __init__(self):
        self.sent: list[str] = []

    async def send(self, text: str) -> None:
        self.sent.append(text)


@pytest.mark.asyncio
async def test_warns_on_consecutive_failures(db):
    srepo = SourceRepo(db)
    sid = await srepo.upsert(
        source_name="flaky",
        source_type="retailer_lottery",
        base_url="https://x",
        trust_score=90,
    )
    now = datetime(2026, 4, 21, 12)
    for i in range(6):
        await srepo.record_failure(sid, now - timedelta(minutes=i), "boom")
    det = SilenceDetector(
        db=db,
        notification_repo=NotificationRepo(db),
        notifier=FakeNotifier(),
    )
    sent = await det.tick(now=now)
    assert sent == 1


@pytest.mark.asyncio
async def test_debounces_within_24h(db):
    srepo = SourceRepo(db)
    sid = await srepo.upsert(
        source_name="flaky",
        source_type="retailer_lottery",
        base_url="https://x",
        trust_score=90,
    )
    now = datetime(2026, 4, 21, 12)
    for i in range(6):
        await srepo.record_failure(sid, now - timedelta(minutes=i), "boom")
    det = SilenceDetector(
        db=db,
        notification_repo=NotificationRepo(db),
        notifier=FakeNotifier(),
    )
    first = await det.tick(now=now)
    second = await det.tick(now=now + timedelta(hours=1))
    assert first == 1
    assert second == 0  # debounced


@pytest.mark.asyncio
async def test_no_warn_if_healthy(db):
    srepo = SourceRepo(db)
    sid = await srepo.upsert(
        source_name="healthy",
        source_type="official_news",
        base_url="https://x",
        trust_score=100,
    )
    now = datetime(2026, 4, 21, 12)
    await srepo.record_success(sid, now - timedelta(minutes=5))
    det = SilenceDetector(
        db=db,
        notification_repo=NotificationRepo(db),
        notifier=FakeNotifier(),
    )
    sent = await det.tick(now=now)
    assert sent == 0


@pytest.mark.asyncio
async def test_suppressed_during_quiet_hours(db):
    """quiet hours (21-10時) の間は監視アラートも送らない。"""
    srepo = SourceRepo(db)
    sid = await srepo.upsert(
        source_name="flaky_night",
        source_type="retailer_lottery",
        base_url="https://x",
        trust_score=90,
    )
    night = datetime(2026, 4, 21, 23, 0)  # 抑止帯
    for i in range(6):
        await srepo.record_failure(sid, night - timedelta(minutes=i), "boom")
    det = SilenceDetector(
        db=db,
        notification_repo=NotificationRepo(db),
        notifier=FakeNotifier(),
    )
    sent = await det.tick(now=night)
    assert sent == 0


@pytest.mark.asyncio
async def test_warns_after_debounce_window(db):
    """24h 経過後は再警告する。"""
    srepo = SourceRepo(db)
    sid = await srepo.upsert(
        source_name="flaky2",
        source_type="retailer_lottery",
        base_url="https://x",
        trust_score=90,
    )
    now = datetime(2026, 4, 21, 12)
    for i in range(6):
        await srepo.record_failure(sid, now - timedelta(minutes=i), "boom")
    det = SilenceDetector(
        db=db,
        notification_repo=NotificationRepo(db),
        notifier=FakeNotifier(),
    )
    first = await det.tick(now=now)
    third = await det.tick(now=now + timedelta(hours=25))
    assert first == 1
    assert third == 1
