from datetime import datetime, timedelta

import pytest
from pokebot.health import DailyReportJob, SilenceDetector
from pokebot.models import Event, EventKind, Priority
from pokebot.storage.repo import EventRepo, SourceHealthRepo


class FakeNotifier:
    def __init__(self):
        self.sent: list[str] = []

    async def send(self, text: str) -> None:
        self.sent.append(text)


@pytest.fixture
def repos(db):
    return EventRepo(db), SourceHealthRepo(db)


@pytest.mark.asyncio
async def test_daily_report_counts_events_and_failures(repos):
    event_repo, health_repo = repos
    now = datetime(2026, 4, 20, 9, 0)
    for i in range(3):
        await event_repo.insert_if_new(Event(
            source="yodobashi", kind=EventKind.LOTTERY_OPEN,
            product_name=f"p{i}", product_raw=f"p{i}",
            normalized_key=f"k{i}", url=f"https://ex.com/{i}",
            detected_at=now - timedelta(hours=1), priority=Priority.CRITICAL,
        ))
    await health_repo.record_failure("bic", now - timedelta(minutes=5), "boom")
    notifier = FakeNotifier()
    job = DailyReportJob(event_repo, health_repo, notifier, hhmm="09:00")
    await job.maybe_run(now=now)
    assert notifier.sent
    msg = notifier.sent[0]
    assert "3" in msg
    assert "bic" in msg


@pytest.mark.asyncio
async def test_daily_report_does_not_fire_outside_window(repos):
    event_repo, health_repo = repos
    notifier = FakeNotifier()
    job = DailyReportJob(event_repo, health_repo, notifier, hhmm="09:00")
    # 10:30 — 窓外
    await job.maybe_run(now=datetime(2026, 4, 20, 10, 30))
    assert not notifier.sent


@pytest.mark.asyncio
async def test_daily_report_dedup_within_same_day(repos):
    event_repo, health_repo = repos
    notifier = FakeNotifier()
    job = DailyReportJob(event_repo, health_repo, notifier, hhmm="09:00")
    now = datetime(2026, 4, 20, 9, 0)
    await job.maybe_run(now=now)
    await job.maybe_run(now=now + timedelta(minutes=5))  # 09:05 も窓内
    assert len(notifier.sent) == 1


@pytest.mark.asyncio
async def test_silence_detector_warns_after_24h_gap(repos):
    _, health_repo = repos
    now = datetime(2026, 4, 20, 12)
    await health_repo.record_success("yodobashi", now - timedelta(days=3), nonzero=True)
    await health_repo.record_success("yodobashi", now, nonzero=False)
    notifier = FakeNotifier()
    det = SilenceDetector(health_repo, notifier)
    await det.tick(now=now)
    assert any("パーサ要確認" in m for m in notifier.sent)


@pytest.mark.asyncio
async def test_silence_detector_warns_on_5_consecutive_failures(repos):
    _, health_repo = repos
    now = datetime(2026, 4, 20, 12)
    for i in range(5):
        await health_repo.record_failure("yodobashi", now - timedelta(minutes=5 - i), "boom")
    notifier = FakeNotifier()
    det = SilenceDetector(health_repo, notifier)
    await det.tick(now=now)
    assert any("ソース異常" in m for m in notifier.sent)


@pytest.mark.asyncio
async def test_silence_detector_suppresses_duplicates_within_6h(repos):
    _, health_repo = repos
    now = datetime(2026, 4, 20, 12)
    for i in range(5):
        await health_repo.record_failure("yodobashi", now, "boom")
    notifier = FakeNotifier()
    det = SilenceDetector(health_repo, notifier)
    await det.tick(now=now)
    await det.tick(now=now + timedelta(hours=1))
    assert len([m for m in notifier.sent if "ソース異常" in m]) == 1
