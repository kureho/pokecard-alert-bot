"""店舗の地域フィルタ。

ユーザーが通知を受けたい地域 (東京近郊 = 1都3県) の店舗 slug だけを通す。
adapter 層で早期に filter することで:
- 不要な body fetch (HTTP request) をスキップできる
- DB に「見ても行けない店舗」の event が溜まらない
- 通知ロジックは従来通り (地域判定を dispatch 側に持たない)

将来ユーザーが地域を追加・変更したくなった場合は、ここを編集するだけで済む。
env 変数での動的 override は現状 YAGNI なので入れていない。
"""

from __future__ import annotations

# カードラボ (c_labo_blog) の URL slug → 所在地メモ。
# 東京都 / 神奈川県 / 埼玉県 / 千葉県 のみ通知対象とする。
CLABO_TOKYO_METRO_SLUGS: frozenset[str] = frozenset(
    {
        "akihabara",     # 東京・秋葉原
        "stakihabara",   # 東京・秋葉原2号店
        "shinjuku",      # 東京・新宿
        "ikebukuro",     # 東京・池袋
        "shibuya",       # 東京・渋谷
        "yokohama",      # 神奈川・横浜
        "tokorozawa",    # 埼玉・所沢
        "tsudanuma",     # 千葉・津田沼
    }
)

# ポケモンセンター (pokemoncenter_store_voice) の shop_key。
# 東京都 / 神奈川県 / 千葉県 のみ通知対象。埼玉は直営店舗なし。
POKECEN_TOKYO_METRO_SHOPS: frozenset[str] = frozenset(
    {
        "megatokyo",     # 東京・日本橋 (メガトウキョー)
        "shibuya",       # 東京・渋谷
        "tokyodx",       # 東京・池袋 (トウキョーDX)
        "skytreetown",   # 東京・押上 (スカイツリータウン)
        "tokyobay",      # 千葉・浦安 (トウキョーベイ)
        "yokohama",      # 神奈川・横浜
    }
)


def is_clabo_tokyo_metro(shop_slug: str) -> bool:
    """カードラボの店舗 slug が東京近郊か。unknown slug は保守的に False。"""
    return shop_slug in CLABO_TOKYO_METRO_SLUGS


def is_pokecen_tokyo_metro(shop_key: str) -> bool:
    """ポケモンセンターの shop_key が東京近郊か。"""
    return shop_key in POKECEN_TOKYO_METRO_SHOPS
