"""archive_stale_events cleanup job のロジック検証。

本番 DB は触らない。tests/conftest.py の `db` fixture (pokebot_test) 上で
以下の3カテゴリを archived に更新する動作を検証する:

  1. non_tokyo_metro: cardlabo / pokemoncenter で東京近郊 allowlist 外の store
  2. apply_ended:     apply_end_at が now より 1h 以上過去
  3. disabled_adapter: amazon / pokecawatch / unknown retailer や Twitter 由来の orphan
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from pokebot.__main__ import archive_stale_events
from pokebot.storage.repos import LotteryEventRepo

NOW = datetime(2026, 5, 1, 12)


async def _insert_active_event(
    db,
    *,
    retailer: str | None,
    store: str | None,
    title: str,
    key: str,
    apply_start_at: datetime | None = None,
    apply_end_at: datetime | None = None,
) -> int:
    repo = LotteryEventRepo(db)
    return await repo.create(
        retailer_name=retailer,
        store_name=store,
        canonical_title=title,
        sales_type="lottery",
        dedupe_key=key,
        apply_start_at=apply_start_at if apply_start_at is not None else NOW + timedelta(days=10),
        apply_end_at=apply_end_at if apply_end_at is not None else NOW + timedelta(days=14),
        source_primary_url="https://ex/" + key,
        confidence_score=90,
        official_confirmation_status="confirmed",
        status="active",
    )


@pytest.mark.asyncio
async def test_dry_run_returns_targets_without_modifying_db(db):
    """dry-run mode: 対象を列挙するが DB は変更しない。"""
    ok_id = await _insert_active_event(
        db, retailer="cardlabo", store="カードラボ秋葉原",
        title="アビスアイ抽選 秋葉原", key="k-aki",
    )
    ng_id = await _insert_active_event(
        db, retailer="cardlabo", store="カードラボ浜松",
        title="アビスアイ抽選 浜松", key="k-hama",
    )

    count, targets = await archive_stale_events(db, execute=False, now=NOW)

    assert count == 1
    assert targets[0]["id"] == ng_id
    assert targets[0]["reason"] == "non_tokyo_metro"
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
    ng_sapporo = await _insert_active_event(
        db, retailer="pokemoncenter", store="ポケモンセンターサッポロ",
        title="アビスアイ抽選 サッポロ", key="k-sapp",
    )
    ok_mega = await _insert_active_event(
        db, retailer="pokemoncenter", store="ポケモンセンターメガトウキョー",
        title="アビスアイ抽選 メガトウキョー", key="k-mega",
    )

    count, targets = await archive_stale_events(db, execute=True, now=NOW)

    assert count == 3
    ids_archived = {r["id"] for r in targets}
    assert ids_archived == {ng_hamamatsu, ng_osaka, ng_sapporo}
    reasons = {r["reason"] for r in targets}
    assert reasons == {"non_tokyo_metro"}

    repo = LotteryEventRepo(db)
    active_ids = {e.id for e in await repo.list_active(limit=100)}
    assert ok_id in active_ids
    assert ok_mega in active_ids
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
    c1, _ = await archive_stale_events(db, execute=True, now=NOW)
    c2, _ = await archive_stale_events(db, execute=True, now=NOW)
    assert c1 == 1
    assert c2 == 0


@pytest.mark.asyncio
async def test_null_store_events_are_not_archived(db):
    """store_name=NULL の chain-wide 告知は non_tokyo_metro 判定では触らない。

    ただし retailer が disabled_adapter 判定に該当する場合 (unknown など) は別カテゴリで対象になる。
    """
    null_store_id = await _insert_active_event(
        db, retailer="cardlabo", store=None,
        title="全店共通告知", key="k-chain",
    )
    other_id = await _insert_active_event(
        db, retailer="pokemoncenter_online", store=None,
        title="online only", key="k-online",
    )

    count, targets = await archive_stale_events(db, execute=True, now=NOW)
    assert count == 0
    assert targets == []

    repo = LotteryEventRepo(db)
    active_ids = {e.id for e in await repo.list_active(limit=100)}
    assert null_store_id in active_ids
    assert other_id in active_ids


@pytest.mark.asyncio
async def test_non_active_events_are_not_touched(db):
    """すでに archived / pending_review の event は対象外。"""
    repo = LotteryEventRepo(db)
    archived_id = await repo.create(
        retailer_name="cardlabo",
        store_name="カードラボ浜松",
        canonical_title="浜松 (archived)",
        sales_type="lottery",
        dedupe_key="k-arch",
        apply_start_at=NOW + timedelta(days=10),
        apply_end_at=NOW + timedelta(days=14),
        source_primary_url="https://ex",
        confidence_score=90,
        official_confirmation_status="confirmed",
        status="archived",
    )

    count, _ = await archive_stale_events(db, execute=True, now=NOW)
    assert count == 0

    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status FROM lottery_events WHERE id = $1", archived_id
        )
    assert row["status"] == "archived"


# ===== 追加カテゴリ: apply_end_at 過去の active =====


@pytest.mark.asyncio
async def test_apply_ended_event_is_archived(db):
    """apply_end_at が now から 1h 以上過去の active event は archive 対象。"""
    ended_id = await _insert_active_event(
        db, retailer="pokemoncenter_online", store="online",
        title="受付終了済み", key="k-ended",
        apply_start_at=NOW - timedelta(days=5),
        apply_end_at=NOW - timedelta(hours=2),
    )
    count, targets = await archive_stale_events(db, execute=True, now=NOW)
    assert count == 1
    assert targets[0]["id"] == ended_id
    assert targets[0]["reason"] == "apply_ended"

    repo = LotteryEventRepo(db)
    active_ids = {e.id for e in await repo.list_active(limit=100)}
    assert ended_id not in active_ids


@pytest.mark.asyncio
async def test_apply_ended_within_grace_stays_active(db):
    """apply_end_at が 1h grace 内なら対象外。"""
    just_ended_id = await _insert_active_event(
        db, retailer="pokemoncenter_online", store="online",
        title="直前終了", key="k-just",
        apply_start_at=NOW - timedelta(days=5),
        apply_end_at=NOW - timedelta(minutes=30),
    )
    count, _ = await archive_stale_events(db, execute=True, now=NOW)
    assert count == 0

    repo = LotteryEventRepo(db)
    active_ids = {e.id for e in await repo.list_active(limit=100)}
    assert just_ended_id in active_ids


@pytest.mark.asyncio
async def test_apply_end_null_is_not_archived_by_ended_rule(db):
    """apply_end_at=NULL の event は apply_ended 判定で触らない (時刻情報なしを保守的に温存)。"""
    unknown_id = await _insert_active_event(
        db, retailer="pokemoncenter_online", store="online",
        title="期限不明", key="k-noend",
        apply_start_at=NOW - timedelta(days=5),
        apply_end_at=None,
    )
    count, _ = await archive_stale_events(db, execute=True, now=NOW)
    assert count == 0

    repo = LotteryEventRepo(db)
    active_ids = {e.id for e in await repo.list_active(limit=100)}
    assert unknown_id in active_ids


# ===== 追加カテゴリ: disabled adapter 由来 orphan =====


@pytest.mark.asyncio
async def test_amazon_retailer_is_archived(db):
    """retailer='amazon' の active event は disabled adapter 由来 orphan として archive。"""
    orphan_id = await _insert_active_event(
        db, retailer="amazon", store="Amazon.co.jp",
        title="amazon 抽選", key="k-amazon",
    )
    count, targets = await archive_stale_events(db, execute=True, now=NOW)
    assert count == 1
    assert targets[0]["id"] == orphan_id
    assert targets[0]["reason"] == "disabled_adapter"


@pytest.mark.asyncio
async def test_pokecawatch_retailer_is_archived(db):
    """retailer='pokecawatch' も disabled adapter 由来。"""
    orphan_id = await _insert_active_event(
        db, retailer="pokecawatch", store=None,
        title="pokecawatch 記事", key="k-pcw",
    )
    count, targets = await archive_stale_events(db, execute=True, now=NOW)
    assert count == 1
    assert targets[0]["id"] == orphan_id
    assert targets[0]["reason"] == "disabled_adapter"


@pytest.mark.asyncio
async def test_twitter_store_name_is_archived(db):
    """store_name が '@' で始まる (Twitter username) は disabled adapter 由来。"""
    orphan_id = await _insert_active_event(
        db, retailer="amazon", store="@pokecayoyaku",
        title="tweet 由来", key="k-tw",
    )
    count, targets = await archive_stale_events(db, execute=True, now=NOW)
    assert count == 1
    assert targets[0]["id"] == orphan_id
    assert targets[0]["reason"] == "disabled_adapter"


@pytest.mark.asyncio
async def test_unknown_retailer_is_archived(db):
    """retailer='unknown' も disabled adapter 由来として archive (retailer_name は NOT NULL)。"""
    unknown_ret_id = await _insert_active_event(
        db, retailer="unknown", store=None,
        title="retailer 不明", key="k-unk",
    )
    count, targets = await archive_stale_events(db, execute=True, now=NOW)
    assert count == 1
    assert targets[0]["id"] == unknown_ret_id
    assert targets[0]["reason"] == "disabled_adapter"


# ===== 追加カテゴリ: 古い pending_review =====


async def _insert_pending_review(
    db, *, title: str, key: str, first_seen_at: datetime
) -> int:
    repo = LotteryEventRepo(db)
    new_id = await repo.create(
        retailer_name="pokemoncenter",
        store_name="ポケモンセンターメガトウキョー",
        canonical_title=title,
        sales_type="unknown",
        dedupe_key=key,
        apply_start_at=None,
        apply_end_at=None,
        source_primary_url="https://ex/" + key,
        confidence_score=56,
        official_confirmation_status="unconfirmed",
        status="pending_review",
    )
    async with db.pool.acquire() as conn:
        await conn.execute(
            "UPDATE lottery_events SET first_seen_at = $1 WHERE id = $2",
            first_seen_at, new_id,
        )
    return new_id


@pytest.mark.asyncio
async def test_old_pending_review_is_archived(db):
    """first_seen_at が 7日より前の pending_review は archive される。"""
    old_id = await _insert_pending_review(
        db, title="販売方法について", key="k-oldpr",
        first_seen_at=NOW - timedelta(days=10),
    )
    count, targets = await archive_stale_events(db, execute=True, now=NOW)
    assert count == 1
    assert targets[0]["id"] == old_id
    assert targets[0]["reason"] == "stale_pending_review"

    repo = LotteryEventRepo(db)
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status FROM lottery_events WHERE id = $1", old_id
        )
    assert row["status"] == "archived"
    # active list に載らない
    active_ids = {e.id for e in await repo.list_active(limit=100)}
    assert old_id not in active_ids


@pytest.mark.asyncio
async def test_recent_pending_review_stays(db):
    """first_seen_at が 7日以内の pending_review は残す (フィルタ調整の余地を残す)。"""
    recent_id = await _insert_pending_review(
        db, title="販売方法について", key="k-recentpr",
        first_seen_at=NOW - timedelta(days=3),
    )
    count, _ = await archive_stale_events(db, execute=True, now=NOW)
    assert count == 0

    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status FROM lottery_events WHERE id = $1", recent_id
        )
    assert row["status"] == "pending_review"


@pytest.mark.asyncio
async def test_mixed_categories_in_single_run(db):
    """3 カテゴリが混在していても全て archive される。"""
    non_tokyo_id = await _insert_active_event(
        db, retailer="cardlabo", store="カードラボ浜松",
        title="浜松", key="k-hama",
    )
    ended_id = await _insert_active_event(
        db, retailer="pokemoncenter_online", store="online",
        title="終了済み", key="k-end",
        apply_start_at=NOW - timedelta(days=5),
        apply_end_at=NOW - timedelta(hours=3),
    )
    orphan_id = await _insert_active_event(
        db, retailer="amazon", store="@x",
        title="twitter orphan", key="k-orph",
    )
    ok_id = await _insert_active_event(
        db, retailer="cardlabo", store="カードラボ秋葉原",
        title="秋葉原", key="k-aki",
    )

    count, targets = await archive_stale_events(db, execute=True, now=NOW)
    assert count == 3
    ids = {t["id"] for t in targets}
    assert ids == {non_tokyo_id, ended_id, orphan_id}

    repo = LotteryEventRepo(db)
    active_ids = {e.id for e in await repo.list_active(limit=100)}
    assert ok_id in active_ids
    assert non_tokyo_id not in active_ids
    assert ended_id not in active_ids
    assert orphan_id not in active_ids
