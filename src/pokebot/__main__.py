from __future__ import annotations

import argparse
import asyncio
import logging
import os
from datetime import datetime

from dotenv import load_dotenv

from . import adapters  # noqa: F401  # side-effect: all adapters register
from .adapters.registry import AdapterRegistry
from .lib.dedupe import build_notification_dedupe_key
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
    "c_labo_blog",
    "amiami_lottery",
    "pokecawatch_chusen",
    "twitter_pokecayoyaku",
    "twitter_pokecamatomeru",
    "twitter_pokecawatch",
    "twitter_beatdown",
    "twitter_ys_info",
    "twitter_usagiya_jounai",
    "twitter_t_sanoTCG",
    "nyuka_now_news",
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
    # Twitter syndication API は連続アクセスで 429 を返すので pacing を入れる
    if source_name.startswith("twitter_"):
        await asyncio.sleep(2)
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


async def _seed_notification_sent(
    notif_repo: NotificationRepo,
    *,
    lottery_event_id: int,
    dedupe_key: str,
    now: datetime,  # noqa: ARG001 - interface互換で残す (sent_at はセットしない)
) -> None:
    """初回スクレイプ時、生成されたイベントに対し new 通知の dedupe_key を予約する。

    次回 dispatch で同じ dedupe_key が try_claim 時に衝突して suppress される (LINE 非送信)。
    ただし **sent_at は NULL のまま** にする: per-day cap は sent_at IS NOT NULL を
    カウントするため、seed 分をカウントに含めないことで実送信数だけが cap の対象になる。
    """
    # dedupe_key は new 通知のものと同一 (UNIQUE 制約で将来の new を suppress)。
    # ただし notification_type は 'seed' で分離して cap 計算から除外する。
    ndk = build_notification_dedupe_key(
        lottery_dedupe_key=dedupe_key,
        notification_type="new",
        content_version="v1",
    )
    await notif_repo.try_claim(
        lottery_event_id=lottery_event_id,
        notification_type="seed",
        channel="line",
        dedupe_key=ndk,
        payload_summary="[first-run seed; not sent]",
    )


async def job_lottery_watch() -> None:
    load_dotenv()
    dsn = os.environ["DATABASE_URL"]
    db = Database(dsn)
    await _bootstrap(db)
    try:
        source_repo = SourceRepo(db)
        product_repo = ProductRepo(db)
        lottery_repo = LotteryEventRepo(db)
        notif_repo = NotificationRepo(db)
        upsert = LotteryEventUpsertService(
            lottery_repo=lottery_repo,
            product_repo=product_repo,
            source_repo=source_repo,
        )
        now = datetime.now()
        total_new = 0
        total_updated = 0
        total_seeded = 0
        for name in LOTTERY_WATCH_ADAPTERS:
            # record_success 前に first_run 判定する
            source_before = await source_repo.get_by_name(name)
            is_first_run = source_before is None or source_before.last_success_at is None
            candidates = await _run_adapter(name, source_repo, now)
            for c in candidates:
                out = await upsert.apply(c, now=now)
                if out is None:
                    continue
                if out.is_new:
                    total_new += 1
                    if is_first_run:
                        await _seed_notification_sent(
                            notif_repo,
                            lottery_event_id=out.event_id,
                            dedupe_key=out.dedupe_key,
                            now=now,
                        )
                        total_seeded += 1
                elif out.is_updated:
                    total_updated += 1
        log.info(
            "lottery_watch complete: new=%d updated=%d first_run_seeded=%d",
            total_new,
            total_updated,
            total_seeded,
        )
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

        # 締切前 alert (apply_end_at が 3h 以内)
        deadline_result = await disp.dispatch_deadlines(now=now)
        log.info(
            "notify_dispatch_deadlines: deadline=%d suppressed=%d",
            deadline_result.update_sent,
            deadline_result.suppressed,
        )

        # Update 通知: 既に new 送信済 event で significant field に変化があったもの
        update_result = await disp.dispatch_updates(now=now)
        log.info(
            "notify_dispatch_updates: update=%d suppressed=%d",
            update_result.update_sent,
            update_result.suppressed,
        )

        # Daily summary (JST 09:00 窓で 1日1回)
        from .services.daily_summary import DailySummaryService

        hhmm = os.environ.get("DAILY_REPORT_JST", "09:00")
        summary = DailySummaryService(
            db=db,
            notification_repo=NotificationRepo(db),
            notifier=notifier,
            hhmm=hhmm,
        )
        fired = await summary.maybe_run(now=now)
        if fired:
            log.info("daily summary fired")

        # Silence Detector: source の連続失敗/長時間無反応を検知して警告
        from .services.silence_detector import SilenceDetector

        silence = SilenceDetector(
            db=db,
            notification_repo=NotificationRepo(db),
            notifier=notifier,
        )
        silence_sent = await silence.tick(now=now)
        if silence_sent:
            log.info("silence warnings sent: %d", silence_sent)
    finally:
        await db.close()


async def job_all() -> None:
    """1 回の cron 呼び出しで product_sync → lottery_watch → notify_dispatch の順。

    GitHub Actions からはこれを呼ぶだけで動くが、分離したい場合は個別ジョブ化可。
    """
    await job_product_sync()
    await job_lottery_watch()
    await job_notify_dispatch()


async def job_audit() -> None:
    """精度検証用: DB 状態を stdout に詳細 dump する。

    - lottery_events の status/sales_type/confidence 内訳
    - status 別に各 30件ずつのタイトル/信頼度
    - 直近の lottery_event_sources (source_published_at, extracted_payload)
    - notifications の送信履歴
    """
    load_dotenv()
    dsn = os.environ["DATABASE_URL"]
    db = Database(dsn)
    await db.init()
    try:
        async with db.pool.acquire() as conn:
            # Status breakdown
            print("=" * 80)
            print("# STATUS × SALES_TYPE BREAKDOWN")
            print("=" * 80)
            rows = await conn.fetch(
                """SELECT status, sales_type, COUNT(*) AS c,
                        AVG(confidence_score)::int AS avg_conf
                   FROM lottery_events
                   GROUP BY status, sales_type
                   ORDER BY status, c DESC"""
            )
            for r in rows:
                print(
                    f"  {r['status']:17} {r['sales_type']:18} "
                    f"count={r['c']:4d} avg_conf={r['avg_conf']}"
                )

            # active events detail
            print()
            print("=" * 80)
            print("# ACTIVE events (通知対象候補):")
            print("=" * 80)
            rows = await conn.fetch(
                """SELECT id, canonical_title, sales_type, confidence_score,
                        official_confirmation_status, retailer_name, store_name,
                        apply_start_at, apply_end_at, first_seen_at, source_primary_url
                   FROM lottery_events WHERE status = 'active'
                   ORDER BY first_seen_at DESC LIMIT 30"""
            )
            for r in rows:
                loc = r["retailer_name"]
                if r["store_name"]:
                    loc = f"{r['retailer_name']}/{r['store_name']}"
                print(
                    f"  [{r['id']:>4}] conf={r['confidence_score']:3d} "
                    f"{r['official_confirmation_status']:12} "
                    f"{r['sales_type']:18} {loc:35} {r['canonical_title'][:45]}"
                )
                print(
                    f"         apply={r['apply_start_at']}→{r['apply_end_at']} "
                    f"url={r['source_primary_url']}"
                )

            # archived sample (published too old)
            print()
            print("=" * 80)
            print("# ARCHIVED events (source_published_at 14日超):")
            print("=" * 80)
            rows = await conn.fetch(
                """SELECT id, canonical_title, sales_type, confidence_score, first_seen_at
                   FROM lottery_events WHERE status = 'archived'
                   ORDER BY first_seen_at DESC LIMIT 15"""
            )
            for r in rows:
                print(
                    f"  [{r['id']:>4}] conf={r['confidence_score']:3d} "
                    f"{r['sales_type']:18} {r['canonical_title'][:50]}"
                )

            # pending_review sample (unknown sales_type)
            print()
            print("=" * 80)
            print("# PENDING_REVIEW events (sales_type=unknown):")
            print("=" * 80)
            rows = await conn.fetch(
                """SELECT id, canonical_title, confidence_score, first_seen_at,
                        source_primary_url
                   FROM lottery_events WHERE status = 'pending_review'
                   ORDER BY first_seen_at DESC LIMIT 15"""
            )
            for r in rows:
                print(
                    f"  [{r['id']:>4}] conf={r['confidence_score']:3d} {r['canonical_title'][:60]}"
                )
                print(f"         url={r['source_primary_url']}")

            # Source extracted payloads sample — 何を抽出できたか
            print()
            print("=" * 80)
            print("# lottery_event_sources 直近10件 (extracted_payload):")
            print("=" * 80)
            rows = await conn.fetch(
                """SELECT les.lottery_event_id, les.source_published_at,
                        les.extracted_payload_json, le.status, le.canonical_title
                   FROM lottery_event_sources les
                   JOIN lottery_events le ON le.id = les.lottery_event_id
                   ORDER BY les.fetched_at DESC LIMIT 10"""
            )
            for r in rows:
                payload = r["extracted_payload_json"] or "{}"
                print(f"  event={r['lottery_event_id']} status={r['status']}")
                print(f"    title={r['canonical_title'][:60]}")
                print(f"    published={r['source_published_at']}")
                print(f"    payload={payload[:200]}")

            # Notifications history
            print()
            print("=" * 80)
            print("# notifications 型別集計 (今日 UTC 0:00 以降 sent):")
            print("=" * 80)
            today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            rows = await conn.fetch(
                """SELECT notification_type,
                          COUNT(*) AS total,
                          COUNT(*) FILTER (WHERE sent_at IS NOT NULL) AS sent_total,
                          COUNT(*) FILTER (WHERE sent_at >= $1) AS sent_today
                   FROM notifications GROUP BY notification_type ORDER BY total DESC""",
                today,
            )
            for r in rows:
                print(
                    f"  {r['notification_type']:10} total={r['total']:4d} "
                    f"sent_all={r['sent_total']:4d} sent_today={r['sent_today']:4d}"
                )

            print()
            print("=" * 80)
            print("# notifications 直近15件:")
            print("=" * 80)
            rows = await conn.fetch(
                """SELECT id, lottery_event_id, notification_type, sent_at, payload_summary
                   FROM notifications ORDER BY created_at DESC LIMIT 15"""
            )
            for r in rows:
                preview = (r["payload_summary"] or "").replace("\n", " | ")[:120]
                sent = r["sent_at"].isoformat() if r["sent_at"] else "-"
                print(
                    f"  [{r['id']:>4}] event={r['lottery_event_id']} "
                    f"{r['notification_type']:7} sent={sent}"
                )
                print(f"    {preview}")

            # sources health
            print()
            print("=" * 80)
            print("# sources 状態:")
            print("=" * 80)
            rows = await conn.fetch("SELECT * FROM sources ORDER BY trust_score DESC, source_name")
            for r in rows:
                succ = r["last_success_at"].isoformat() if r["last_success_at"] else "-"
                err = (r["last_error"] or "")[:60]
                print(
                    f"  {r['source_name']:38} trust={r['trust_score']:3d} "
                    f"fail={r['consecutive_failures']:3d} success={succ}"
                )
                if err:
                    print(f"    last_error: {err}")
    finally:
        await db.close()


def main() -> None:
    parser = argparse.ArgumentParser("pokebot")
    parser.add_argument(
        "job",
        nargs="?",
        default="all",
        choices=[
            "all",
            "product-sync",
            "lottery-watch",
            "notify-dispatch",
            "bootstrap",
            "audit",
        ],
    )
    args = parser.parse_args()

    setup_logging(level=os.environ.get("LOG_LEVEL", "INFO"))

    job_map = {
        "all": job_all,
        "product-sync": job_product_sync,
        "lottery-watch": job_lottery_watch,
        "notify-dispatch": job_notify_dispatch,
        "audit": job_audit,
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
