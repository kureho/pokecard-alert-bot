from __future__ import annotations

import logging
from datetime import datetime, timedelta

from .storage.repo import EventRepo

log = logging.getLogger(__name__)

DEFAULT_RETENTION = timedelta(days=180)


async def prune_old_events(
    repo: EventRepo, *, now: datetime, retain: timedelta = DEFAULT_RETENTION
) -> int:
    cutoff = now - retain
    async with repo.pool.acquire() as conn:
        status = await conn.execute(
            "DELETE FROM events WHERE notified_at IS NOT NULL AND notified_at < $1",
            cutoff,
        )
    # asyncpg returns "DELETE <n>"
    try:
        deleted = int(status.split()[-1])
    except (ValueError, IndexError):
        deleted = 0
    if deleted:
        log.info("pruned %d old events (< %s)", deleted, cutoff.isoformat())
    return deleted
