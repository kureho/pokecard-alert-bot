"""archive_non_tokyo_metro cleanup job のロジック検証。

本番 DB は触らない。tests/conftest.py の `db` fixture (pokebot_test) 上で
allowlist 外の event を archived に更新する動作を検証する。
"""

from __future__ import annotations

from datetime import datetime

import pytest

from pokebot.__main__ import archive_non_tokyo_metro
from pokebot.storage.repos import LotteryEventRepo


async def _insert_active_event(
    db, *, retailer: str, store: str | None, title: str, key: str
) -> int:
    repo = LotteryEventRepo(db)
    return await repo.create(
        retailer_name=retailer,
        store_name=store,
        canonical_title=title,
        sales_type="lottery",
        dedupe_key=key,
        apply_start_at=datetime(2026, 5, 10, 14),
        apply_end_at=datetime(2026, 5, 14, 23, 59),
        source_primary_url="https://ex/" + key,
        confidence_score=90,
        official_confirmation_status="confirmed",
        status="active",
    )


@pytest.mark.asyncio
async def test_dry_run_returns_targets_without_modifying_db(db):
    """dry-run mode: 対象を列挙するが DB は変更しない。"""
    # 東京近郊 (残す)
    ok_id = await _insert_active_event(
        db, retailer="cardlabo", store="カードラボ秋葉原",
        title="アビスアイ抽選 秋葉原", key="k-aki",
    )
    # 地方 (archive 対象)
    ng_id = await _insert_active_event(
        db, retailer="cardlabo", store="カードラボ浜松",
        title="アビスアイ抽選 浜松", key="k-hama",
    )

    count, targets = await archive_non_tokyo_metro(db, execute=False)

    assert count == 1
    assert targets[0]["id"] == ng_id
    # DB は変更されていない (両方 active のまま)
    repo = LotteryEventRepo(db)
    active_ids = {e.id for e in await repo.list_active(limit=100)}
    assert ok_id in active_ids
    assert ng_id in active_ids


@pytest.mark.asyncio
async def test_execute_archives_only_non_tokyo_metro(db):
    """execute=True: 東京近郊以外だけを archived にする。"""
    ok_id = await _insert_active_event(
        db, retailer="cardlabo", store="カードラボ秋葉原",
        title="アビスアイ抽選 秋葉原", key="k-aki",
    )
    ng_hamamatsu = await _insert_active_event(
        db, retailer="cardlabo", store="カードラボ浜松",
        title="アビスアイ抽選 浜松", key="k-hama",
    )
    ng_osaka = await _insert_active_event(
        db, retailer="cardlabo", store="カードラボ大阪",
        title="アビスアイ抽選 大阪", key="k-osaka",
    )
    # ポケセン: 地方 (対象)
    ng_sapporo = await _insert_active_event(
        db, retailer="pokemoncenter", store="ポケモンセンターサッポロ",
        title="アビスアイ抽選 サッポロ", key="k-sapp",
    )
    # ポケセン: 東京近郊 (残す)
    ok_mega = await _insert_active_event(
        db, retailer="pokemoncenter", store="ポケモンセンターメガトウキョー",
        title="アビスアイ抽選 メガトウキョー", key="k-mega",
    )

    count, targets = await archive_non_tokyo_metro(db, execute=True)

    assert count == 3
    ids_archived = {r["id"] for r in targets}
    assert ids_archived == {ng_hamamatsu, ng_osaka, ng_sapporo}

    # 東京近郊は active のまま
    repo = LotteryEventRepo(db)
    active_ids = {e.id for e in await repo.list_active(limit=100)}
    assert ok_id in active_ids
    assert ok_mega in active_ids
    # 地方は active から消えた
    assert ng_hamamatsu not in active_ids
    assert ng_osaka not in active_ids
    assert ng_sapporo not in active_ids


@pytest.mark.asyncio
async def test_idempotent_on_second_run(db):
    """2回目以降は対象 0 件 (冪等性)。"""
    await _insert_active_event(
        db, retailer="cardlabo", store="カードラボ浜松",
        title="浜松", key="k-hama",
    )
    c1, _ = await archive_non_tokyo_metro(db, execute=True)
    c2, _ = await archive_non_tokyo_metro(db, execute=True)
    assert c1 == 1
    assert c2 == 0


@pytest.mark.asyncio
async def test_null_store_events_are_not_archived(db):
    """store_name=NULL の chain-wide 告知 (公式 retailer 全体など) は触らない。

    カードラボ / ポケモンセンター retailer でも、店舗未指定なら保守的に温存する。
    """
    # あり得ないケースだが念のため: retailer=cardlabo, store=NULL
    null_store_id = await _insert_active_event(
        db, retailer="cardlabo", store=None,
        title="全店共通告知", key="k-chain",
    )
    # allowlist にない retailer は触らない (対象 retailer は cardlabo / pokemoncenter のみ)
    other_id = await _insert_active_event(
        db, retailer="pokemoncenter_online", store=None,
        title="online only", key="k-online",
    )

    count, _ = await archive_non_tokyo_metro(db, execute=True)
    assert count == 0

    repo = LotteryEventRepo(db)
    active_ids = {e.id for e in await repo.list_active(limit=100)}
    assert null_store_id in active_ids
    assert other_id in active_ids


@pytest.mark.asyncio
async def test_non_active_events_are_not_touched(db):
    """すでに archived / pending_review の event は対象外。"""
    repo = LotteryEventRepo(db)
    # 直接 archived で insert
    archived_id = await repo.create(
        retailer_name="cardlabo",
        store_name="カードラボ浜松",
        canonical_title="浜松 (archived)",
        sales_type="lottery",
        dedupe_key="k-arch",
        apply_start_at=datetime(2026, 5, 10, 14),
        apply_end_at=datetime(2026, 5, 14, 23, 59),
        source_primary_url="https://ex",
        confidence_score=90,
        official_confirmation_status="confirmed",
        status="archived",
    )

    count, _ = await archive_non_tokyo_metro(db, execute=True)
    assert count == 0

    # 元々 archived のものは触られていない
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status FROM lottery_events WHERE id = $1", archived_id
        )
    assert row["status"] == "archived"
