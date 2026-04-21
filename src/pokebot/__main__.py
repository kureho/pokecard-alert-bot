from __future__ import annotations

import argparse
import asyncio
import logging
import os
from datetime import datetime

from dotenv import load_dotenv

from . import adapters  # noqa: F401  # side-effect: all adapters register
from .adapters.registry import AdapterRegistry
from .logging_setup import setup_logging
from .notify.line import DryRunNotifier, LineNotifier, Notifier
from .seeds import seed_sources
from .services.lottery_upsert import LotteryEventUpsertService
from .services.notification import (
    DEFAULT_MAX_PER_DAY,
    DEFAULT_MAX_PER_RUN,
    NotificationDispatcher,
)
from .services.product_sync import ProductSyncService
from .storage.db import Database
from .storage.repos import (
    LotteryEventRepo,
    NotificationRepo,
    ProductRepo,
    SourceRepo,
)

log = logging.getLogger("pokebot")

# 各 Job に含める adapter (sources テーブル側の source_name と一致)
PRODUCT_SYNC_ADAPTERS = ["pokemon_official_products"]
LOTTERY_WATCH_ADAPTERS = [
    "pokemon_official_news",
    "pokemoncenter_online_lottery",
    "pokemoncenter_online_guide",
    "pokemoncenter_store_voice",
    "yodobashi_lottery",
    "biccamera_lottery",
]


def _is_dry_run() -> bool:
    return os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes")


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _make_notifier() -> Notifier:
    if _is_dry_run():
        log.warning("DRY_RUN mode: LINE 実送信を抑止")
        return DryRunNotifier()
    return LineNotifier(
        token=os.environ["LINE_CHANNEL_ACCESS_TOKEN"],
        user_id=os.environ["LINE_USER_ID"],
    )


async def _run_adapter(source_name: str, source_repo: SourceRepo, now: datetime) -> list:
    adapter = AdapterRegistry.get(source_name)
    if not adapter:
        log.warning("adapter not found: %s", source_name)
        return []
    source = await source_repo.get_by_name(source_name)
    try:
        candidates = await adapter.run()
        log.info("adapter %s returned %d candidates", source_name, len(candidates))
        if source:
            await source_repo.record_success(source.id, now)
        return candidates
    except Exception as e:  # noqa: BLE001
        log.warning("adapter %s failed: %s", source_name, e)
        if source:
            await source_repo.record_failure(source.id, now, str(e)[:500])
        return []


async def _bootstrap(db: Database) -> None:
    await db.init()
    await seed_sources(SourceRepo(db))


async def job_product_sync() -> None:
    load_dotenv()
    dsn = os.environ["DATABASE_URL"]
    db = Database(dsn)
    await _bootstrap(db)
    try:
        source_repo = SourceRepo(db)
        product_repo = ProductRepo(db)
        sync = ProductSyncService(product_repo)
        now = datetime.now()
        for name in PRODUCT_SYNC_ADAPTERS:
            candidates = await _run_adapter(name, source_repo, now)
            if candidates:
                await sync.apply(candidates)
        log.info("product_sync complete")
    finally:
        await db.close()


async def job_lottery_watch() -> None:
    load_dotenv()
    dsn = os.environ["DATABASE_URL"]
    db = Database(dsn)
    await _bootstrap(db)
    try:
        source_repo = SourceRepo(db)
        product_repo = ProductRepo(db)
        lottery_repo = LotteryEventRepo(db)
        upsert = LotteryEventUpsertService(
            lottery_repo=lottery_repo,
            product_repo=product_repo,
            source_repo=source_repo,
        )
        now = datetime.now()
        total_new = 0
        total_updated = 0
        for name in LOTTERY_WATCH_ADAPTERS:
            candidates = await _run_adapter(name, source_repo, now)
            for c in candidates:
                out = await upsert.apply(c, now=now)
                if out is None:
                    continue
                if out.is_new:
                    total_new += 1
                elif out.is_updated:
                    total_updated += 1
        log.info("lottery_watch complete: new=%d updated=%d", total_new, total_updated)
    finally:
        await db.close()


async def job_notify_dispatch() -> None:
    load_dotenv()
    dsn = os.environ["DATABASE_URL"]
    db = Database(dsn)
    await _bootstrap(db)
    try:
        notifier = _make_notifier()
        disp = NotificationDispatcher(
            lottery_repo=LotteryEventRepo(db),
            product_repo=ProductRepo(db),
            notification_repo=NotificationRepo(db),
            notifier=notifier,
            max_per_run=_env_int("MAX_NOTIFY_PER_RUN", DEFAULT_MAX_PER_RUN),
            max_per_day=_env_int("MAX_NOTIFY_PER_DAY", DEFAULT_MAX_PER_DAY),
        )
        now = datetime.now()
        result = await disp.dispatch(now=now)
        log.info(
            "notify_dispatch: new=%d update=%d suppressed=%d skipped_low=%d",
            result.new_sent,
            result.update_sent,
            result.suppressed,
            result.skipped_low_confidence,
        )
    finally:
        await db.close()


async def job_all() -> None:
    """1 回の cron 呼び出しで product_sync → lottery_watch → notify_dispatch の順。

    GitHub Actions からはこれを呼ぶだけで動くが、分離したい場合は個別ジョブ化可。
    """
    await job_product_sync()
    await job_lottery_watch()
    await job_notify_dispatch()


def main() -> None:
    parser = argparse.ArgumentParser("pokebot")
    parser.add_argument(
        "job",
        nargs="?",
        default="all",
        choices=["all", "product-sync", "lottery-watch", "notify-dispatch", "bootstrap"],
    )
    args = parser.parse_args()

    setup_logging(level=os.environ.get("LOG_LEVEL", "INFO"))

    job_map = {
        "all": job_all,
        "product-sync": job_product_sync,
        "lottery-watch": job_lottery_watch,
        "notify-dispatch": job_notify_dispatch,
    }
    if args.job == "bootstrap":

        async def _bs():
            load_dotenv()
            db = Database(os.environ["DATABASE_URL"])
            await _bootstrap(db)
            await db.close()

        asyncio.run(_bs())
        return
    asyncio.run(job_map[args.job]())


if __name__ == "__main__":
    main()
