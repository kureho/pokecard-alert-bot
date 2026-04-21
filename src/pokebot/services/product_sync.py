from __future__ import annotations

import logging
from datetime import date

from ..adapters.base import Candidate
from ..storage.repos import ProductRepo

log = logging.getLogger(__name__)


class ProductSyncService:
    """adapter が返した product_master_hint を products テーブルに upsert する。"""

    def __init__(self, repo: ProductRepo) -> None:
        self._repo = repo

    async def apply(self, candidates: list[Candidate]) -> int:
        """hint のみを拾って upsert。通常の lottery candidate は無視。Return: upsert 件数。"""
        count = 0
        for c in candidates:
            payload = c.extracted_payload or {}
            if not payload.get("is_product_master_hint"):
                continue
            release_iso = payload.get("release_date")
            release_d: date | None = None
            if release_iso:
                try:
                    release_d = date.fromisoformat(release_iso)
                except ValueError:
                    release_d = None
            pid = await self._repo.upsert(
                canonical_name=c.product_name_raw,
                normalized_name=c.product_name_normalized or c.product_name_raw,
                release_date=release_d,
                product_type=payload.get("product_type"),
                official_product_url=payload.get("official_product_url") or c.source_url,
                official_news_url=c.source_url,
            )
            # alias 追加（正規化前の生タイトルもキーに残す）
            if c.product_name_raw and c.product_name_raw != c.product_name_normalized:
                await self._repo.add_alias(
                    pid, c.product_name_raw, c.product_name_normalized or c.product_name_raw,
                )
            count += 1
        if count:
            log.info("product_sync: upserted %d products", count)
        return count
