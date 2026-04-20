import os

import pytest_asyncio

from pokebot.storage.db import Database

TEST_DSN = os.environ.get("TEST_DATABASE_URL", "postgresql:///pokebot_test")


@pytest_asyncio.fixture
async def db():
    d = Database(TEST_DSN)
    await d.init()
    async with d.pool.acquire() as conn:
        await conn.execute(
            "TRUNCATE events, product_aliases, source_health, pending_aggregations "
            "RESTART IDENTITY CASCADE;"
        )
    yield d
    await d.close()
