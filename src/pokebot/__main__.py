from __future__ import annotations

import asyncio
import logging
import os

from dotenv import load_dotenv

from .logging_setup import setup_logging
from .seeds import seed_sources
from .storage.db import Database
from .storage.repos import SourceRepo

log = logging.getLogger("pokebot")


async def _run() -> None:
    load_dotenv()
    dsn = os.environ["DATABASE_URL"]
    db = Database(dsn)
    await db.init()
    try:
        # Phase 1 migration applied via schema.py on init().
        # Seed sources (idempotent).
        await seed_sources(SourceRepo(db))
        log.info("bootstrap complete (schema + sources seed). Phase 1 adapters wire-up pending.")
    finally:
        await db.close()


def main() -> None:
    setup_logging(level=os.environ.get("LOG_LEVEL", "INFO"))
    asyncio.run(_run())


if __name__ == "__main__":
    main()
