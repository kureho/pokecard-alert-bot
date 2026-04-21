from datetime import datetime
from pokebot.lib.dedupe import (
    build_lottery_dedupe_key, build_notification_dedupe_key,
)


def test_dedupe_key_is_stable():
    k1 = build_lottery_dedupe_key(
        normalized_product="アビスアイ",
        normalized_retailer="pokemoncenter_online",
        normalized_store=None,
        sales_type="lottery",
        apply_start_at=datetime(2026, 5, 10, 14),
        apply_end_at=datetime(2026, 5, 14, 23, 59),
    )
    k2 = build_lottery_dedupe_key(
        normalized_product="アビスアイ",
        normalized_retailer="pokemoncenter_online",
        normalized_store=None,
        sales_type="lottery",
        apply_start_at=datetime(2026, 5, 10, 14),
        apply_end_at=datetime(2026, 5, 14, 23, 59),
    )
    assert k1 == k2
    assert "アビスアイ" in k1
    assert "2026-05-10T14:00" in k1


def test_dedupe_key_differs_by_store():
    common = dict(
        normalized_product="アビスアイ",
        normalized_retailer="pokemoncenter",
        sales_type="lottery",
        apply_start_at=datetime(2026, 5, 10, 14),
        apply_end_at=None,
    )
    k1 = build_lottery_dedupe_key(normalized_store="megatokyo", **common)
    k2 = build_lottery_dedupe_key(normalized_store="shibuya", **common)
    assert k1 != k2


def test_notification_dedupe_key_composed():
    nk = build_notification_dedupe_key(
        lottery_dedupe_key="k1", notification_type="new"
    )
    assert nk.startswith("k1#new#")
