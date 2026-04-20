from datetime import datetime, timedelta
from pathlib import Path

import pytest

from pokebot.models import Event, EventKind, Priority
from pokebot.monitors.html import HtmlMonitor
from pokebot.notify.aggregation import AggregationBuffer
from pokebot.notify.worker import NotifyWorker
from pokebot.parsers.yodobashi import lottery_list
from pokebot.sink import make_sink
from pokebot.storage.repo import EventRepo, SourceHealthRepo


class FakeNotifier:
    def __init__(self):
        self.sent: list[str] = []

    async def send(self, text: str) -> None:
        self.sent.append(text)


@pytest.mark.asyncio
async def test_detect_and_notify_box_lottery(httpx_mock, db):
    fixture = Path("tests/fixtures/yodobashi_lottery.html").read_text(encoding="utf-8")
    httpx_mock.add_response(url="https://www.yodobashi.com/lottery", text=fixture)
    event_repo = EventRepo(db)
    health_repo = SourceHealthRepo(db)
    notifier = FakeNotifier()
    aggregator = AggregationBuffer(event_repo)
    monitor = HtmlMonitor(
        id_="yodobashi_lottery",
        url="https://www.yodobashi.com/lottery",
        interval_sec=60,
        parser=lottery_list,
    )
    now = datetime(2026, 4, 20, 12)
    # 初回スクレイプ時の過去ニュース洪水防止フックを迂回するため、健康履歴を先に注入
    await health_repo.record_success(monitor.id, now - timedelta(minutes=5), nonzero=False)
    sink = make_sink(event_repo, health_repo, now_fn=lambda: now)
    items = await monitor.fetch()
    await sink(monitor.id, items, True)
    worker = NotifyWorker(event_repo, notifier, aggregator=aggregator)
    await worker.tick(now=now + timedelta(seconds=10))
    # BOX 抽選は 🔥 付きで届く
    fire = [m for m in notifier.sent if m.startswith("🔥")]
    assert fire, f"expected fire message, got {notifier.sent}"


@pytest.mark.asyncio
async def test_duplicate_source_becomes_aggregation(httpx_mock, db):
    fixture = Path("tests/fixtures/yodobashi_lottery.html").read_text(encoding="utf-8")
    event_repo = EventRepo(db)
    health_repo = SourceHealthRepo(db)
    notifier = FakeNotifier()
    aggregator = AggregationBuffer(event_repo)

    # 別ソースからの同一商品検知を再現するため、source のみ書き換えるラッパを使う。
    # normalized_key は URL ハッシュに依存するので、URL は保持する。
    async def bic_parser(html: str):
        items = await lottery_list(html)
        rewritten = []
        for i in items:
            from pokebot.monitors.types import RawItem

            rewritten.append(
                RawItem(
                    source="bic",
                    raw_title=i.raw_title,
                    url=i.url,
                    kind_hint=i.kind_hint,
                )
            )
        return rewritten

    httpx_mock.add_response(url="https://example.invalid/1", text=fixture)
    httpx_mock.add_response(url="https://example.invalid/2", text=fixture)
    monitor1 = HtmlMonitor("yodobashi_lottery", "https://example.invalid/1", 60, lottery_list)
    monitor2 = HtmlMonitor("bic_lottery", "https://example.invalid/2", 60, bic_parser)

    now = datetime(2026, 4, 20, 12)
    # 初回洪水防止フックの迂回
    await health_repo.record_success(monitor1.id, now - timedelta(minutes=5), nonzero=False)
    await health_repo.record_success(monitor2.id, now - timedelta(minutes=5), nonzero=False)
    sink = make_sink(event_repo, health_repo, now_fn=lambda: now)
    await sink(monitor1.id, await monitor1.fetch(), True)
    worker = NotifyWorker(event_repo, notifier, aggregator=aggregator)
    await worker.tick(now=now)
    baseline = len(notifier.sent)
    assert baseline > 0  # 1回目の即時送信

    # 2件目を 1 分後に検知 → buffer
    await sink(monitor2.id, await monitor2.fetch(), True)
    await worker.tick(now=now + timedelta(minutes=1))
    assert len(notifier.sent) == baseline  # まだ集約されず

    # 12分後 → 集約通知が1本追加される
    await worker.tick(now=now + timedelta(minutes=12))
    aggregation = [m for m in notifier.sent if m.startswith("📌")]
    assert aggregation, f"expected aggregation, got {notifier.sent}"


@pytest.mark.asyncio
async def test_unnotified_events_retry_across_ticks(db):
    event_repo = EventRepo(db)
    ev = Event(
        source="yodobashi",
        kind=EventKind.LOTTERY_OPEN,
        product_name="テラスタルフェスex BOX",
        product_raw="raw",
        normalized_key="k",
        url="https://x",
        detected_at=datetime(2026, 4, 20, 12),
        priority=Priority.CRITICAL,
    )
    await event_repo.insert_if_new(ev)

    calls = {"n": 0}

    class FlakyNotifier:
        def __init__(self):
            self.sent = []

        async def send(self, text):
            calls["n"] += 1
            if calls["n"] <= 2:
                raise RuntimeError("net")
            self.sent.append(text)

    notifier = FlakyNotifier()
    worker = NotifyWorker(event_repo, notifier)
    await worker.tick(now=datetime(2026, 4, 20, 12, 1))
    assert notifier.sent  # tenacity 内で 3 回目が成功
