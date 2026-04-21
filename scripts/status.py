"""pokecard-alert-bot の状態確認 CLI.

使い方 (DATABASE_URL 必要):
  python scripts/status.py products
  python scripts/status.py events
  python scripts/status.py notifications
  python scripts/status.py sources
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from dotenv import load_dotenv

from pokebot.storage.db import Database
from pokebot.storage.repos import (
    LotteryEventRepo,
    ProductRepo,
    SourceRepo,
)


def _fmt_dt(dt) -> str:
    return dt.strftime("%Y-%m-%d %H:%M") if dt else "-"


async def show_products(db: Database, limit: int) -> None:
    repo = ProductRepo(db)
    products = await repo.list_all(limit=limit)
    print(f"# products ({len(products)})")
    for p in products:
        print(f"  [{p.id:>4}] {p.canonical_name:40} release={p.release_date} type={p.product_type}")


async def show_events(db: Database, limit: int) -> None:
    repo = LotteryEventRepo(db)
    events = await repo.list_active(limit=limit)
    print(f"# lottery_events (active={len(events)})")
    for e in events:
        location = e.retailer_name
        if e.store_name:
            location = f"{e.retailer_name}/{e.store_name}"
        print(
            f"  [{e.id:>4}] {e.canonical_title[:40]:40} "
            f"{location:30} {e.sales_type:15} "
            f"conf={e.confidence_score:3d} {e.official_confirmation_status:12} "
            f"apply={_fmt_dt(e.apply_start_at)}→{_fmt_dt(e.apply_end_at)}"
        )


async def show_notifications(db: Database, limit: int) -> None:
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT n.id, n.notification_type, n.sent_at, n.payload_summary
               FROM notifications n ORDER BY n.created_at DESC LIMIT $1""",
            limit,
        )
    print(f"# notifications ({len(rows)})")
    for r in rows:
        sent = _fmt_dt(r["sent_at"])
        preview = (r["payload_summary"] or "").replace("\n", " | ")[:80]
        print(f"  [{r['id']:>4}] {r['notification_type']:7} sent={sent} {preview}")


async def show_sources(db: Database) -> None:
    repo = SourceRepo(db)
    sources = await repo.list_active()
    print(f"# sources (active={len(sources)})")
    async with db.pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM sources ORDER BY trust_score DESC, source_name")
    for r in rows:
        print(
            f"  {r['source_name']:38} trust={r['trust_score']:3d} "
            f"active={r['is_active']} success={_fmt_dt(r['last_success_at'])} "
            f"fails={r['consecutive_failures']} "
            f"err={(r['last_error'] or '')[:60]}"
        )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("cmd", choices=["products", "events", "notifications", "sources"])
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()

    load_dotenv()
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL not set", file=sys.stderr)
        sys.exit(1)
    db = Database(dsn)
    await db.init()
    try:
        if args.cmd == "products":
            await show_products(db, args.limit)
        elif args.cmd == "events":
            await show_events(db, args.limit)
        elif args.cmd == "notifications":
            await show_notifications(db, args.limit)
        elif args.cmd == "sources":
            await show_sources(db)
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
