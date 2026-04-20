import pytest

from pokebot.storage.db import Database


@pytest.mark.asyncio
async def test_schema_creates_all_tables(db):
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
        )
    names = {r["tablename"] for r in rows}
    assert {"events", "product_aliases", "source_health", "pending_aggregations"}.issubset(names)


@pytest.mark.asyncio
async def test_schema_is_idempotent():
    from tests.conftest import TEST_DSN

    d = Database(TEST_DSN)
    await d.init()
    await d.init()  # 再実行しても壊れない
    await d.close()
