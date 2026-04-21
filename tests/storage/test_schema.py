import pytest


@pytest.mark.asyncio
async def test_schema_has_all_phase1_tables(db):
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
        )
    names = {r["tablename"] for r in rows}
    required = {"products", "product_aliases", "sources", "lottery_events",
                "lottery_event_sources", "notifications"}
    missing = required - names
    assert not missing, f"missing tables: {missing}"
