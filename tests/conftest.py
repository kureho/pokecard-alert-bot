import os

import pytest_asyncio

from pokebot.seeds import seed_sources
from pokebot.storage.db import Database
from pokebot.storage.repos import SourceRepo

TEST_DSN = os.environ.get("TEST_DATABASE_URL", "postgresql:///pokebot_test")


@pytest_asyncio.fixture
async def db():
    d = Database(TEST_DSN)
    await d.init()
    async with d.pool.acquire() as conn:
        await conn.execute(
            "TRUNCATE notifications, lottery_event_sources, lottery_events, "
            "product_aliases, products, sources RESTART IDENTITY CASCADE;"
        )
    yield d
    await d.close()


@pytest_asyncio.fixture
async def seeded_db(db):
    await seed_sources(SourceRepo(db))
    return db
