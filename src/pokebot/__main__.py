from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from .config import load_sources
from .monitors.base import Monitor
from .notify.aggregation import AggregationBuffer
from .notify.line import LineNotifier
from .notify.worker import NotifyWorker
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
        await worker.tick(now=datetime.now())
        log.info("tick complete")
    finally:
        await db.close()


def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    asyncio.run(run_once())


if __name__ == "__main__":
    main()
