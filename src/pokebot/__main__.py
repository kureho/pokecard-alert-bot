from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from .config import load_sources
from .health import DailyReportJob, SilenceDetector
from .monitors.base import Monitor
from .notify.aggregation import AggregationBuffer
from .notify.line import LineNotifier
from .notify.worker import NotifyWorker
from .retention import prune_old_events
from .sink import make_sink
from .storage.db import Database
from .storage.repo import EventRepo, SourceHealthRepo

log = logging.getLogger("pokebot")


async def _fetch_monitor(monitor: Monitor, sink) -> None:
    try:
        items = await monitor.fetch()
        await sink(monitor.id, list(items), True)
    except Exception as e:  # noqa: BLE001
        log.warning("monitor %s failed: %s", monitor.id, e)
        await sink(monitor.id, [], False, err=e)


async def run_once() -> None:
    load_dotenv()
    dsn = os.environ["DATABASE_URL"]
    db = Database(dsn)
    await db.init()
    try:
        event_repo = EventRepo(db)
        health_repo = SourceHealthRepo(db)
        notifier = LineNotifier(
            token=os.environ["LINE_CHANNEL_ACCESS_TOKEN"],
            user_id=os.environ["LINE_USER_ID"],
        )
        sources_path = Path(os.environ.get("SOURCES_YAML", "config/sources.yaml"))
        monitors = load_sources(sources_path)

        sink = make_sink(event_repo, health_repo)

        log.info("fetching %d monitors", len(monitors))
        await asyncio.gather(
            *(_fetch_monitor(m, sink) for m in monitors),
            return_exceptions=False,
        )

        aggregator = AggregationBuffer(event_repo)
        worker = NotifyWorker(event_repo, notifier, aggregator=aggregator)
        now = datetime.now()
        await worker.tick(now=now)

        # 日次稼働レポート（JST 指定時刻の窓内で1回だけ発火）
        hhmm = os.environ.get("DAILY_REPORT_JST", "09:00")
        daily_report = DailyReportJob(event_repo, health_repo, notifier, hhmm=hhmm)
        await daily_report.maybe_run(now=now)

        # 死活監視（パーサ無言検知 + 連続失敗警告）
        silence_detector = SilenceDetector(health_repo, notifier)
        await silence_detector.tick(now=now)

        # Retention: JST 04:00 台で events を180日で削除（冪等なので重複OK）
        if now.hour == 4:
            await prune_old_events(event_repo, now=now)

        log.info("tick complete")
    finally:
        await db.close()


def main() -> None:
    from .logging_setup import setup_logging

    setup_logging(level=os.environ.get("LOG_LEVEL", "INFO"))
    asyncio.run(run_once())


if __name__ == "__main__":
    main()
