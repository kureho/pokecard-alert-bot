import pytest
from pokebot.lib.normalize import (
    normalize_product_name, normalize_retailer, normalize_store,
)


@pytest.mark.parametrize("raw,expected", [
    ("アビスアイ", "アビスアイ"),
    ("拡張パック アビスアイ", "アビスアイ"),
    ("ポケモンカードゲーム 拡張パック アビスアイ", "アビスアイ"),
    ("アビスアイ BOX", "アビスアイ"),
    ("アビスアイ 1BOX", "アビスアイ"),
    ("ポケモンカード アビスアイ ボックス", "アビスアイ"),
    ("強化拡張パック シャイニートレジャーex BOX", "シャイニートレジャーex"),
    ("ハイクラスパック テラスタルフェスex BOX", "テラスタルフェスex"),
])
def test_normalize_product_strips_decorators(raw, expected):
    assert normalize_product_name(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("ポケモンセンターオンライン", "pokemoncenter_online"),
    ("ヨドバシ.com", "yodobashi"),
    ("ビックカメラ", "biccamera"),
    ("Amazon", "amazon"),
    ("ジョーシン", "joshin"),
    ("ヤマダ電機", "yamada"),
])
def test_normalize_retailer(raw, expected):
    assert normalize_retailer(raw) == expected


def test_normalize_store_strips_pokecen_prefix():
    assert normalize_store("ポケモンセンターメガトウキョー") == "メガトウキョー"
    assert normalize_store(None) is None
