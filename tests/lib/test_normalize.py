import pytest
from pokebot.lib.normalize import (
    extract_known_product_name,
    normalize_product_name,
    normalize_retailer,
    normalize_store,
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
    # c_labo 複数店舗で違う body h1 → 同じ商品名に収束
    ("【5月22日発売】ポケモンカードゲーム MEGA 拡張パック アビスアイ抽選予約販売のお知らせ", "アビスアイ"),
    ("【ポケモンカードゲーム】5月22日(金)発売「アビスアイ」 抽選販売について", "アビスアイ"),
    ("【5/22発売】 ポケモンカードゲーム MEGA 拡張パック アビスアイ抽選予約・販売のお知らせ", "アビスアイ"),
    ("MEGA拡張パック『アビスアイ』 抽選販売のお知らせ", "アビスアイ"),
    ("5月22日発売商品「アビスアイ」の抽選予約販売について", "アビスアイ"),
    # 別商品でも同様
    ("【2月16日】ニンジャスピナー 抽選予約情報", "ニンジャスピナー"),
    ("強化拡張パック ポケモンカード151 BOX", "ポケモンカード151"),
    # 既知商品が含まれない場合は従来の normalize にフォールバック
    ("強化拡張パック 未知商品 BOX", "未知商品"),
])
def test_normalize_known_products_converge(raw, expected):
    assert normalize_product_name(raw) == expected


def test_extract_known_longest_match():
    # MEGAドリームex が ドリーム より優先
    assert extract_known_product_name("MEGAドリームex 抽選販売") == "MEGAドリームex"


def test_extract_known_returns_none_when_absent():
    assert extract_known_product_name("完全に未知の商品名") is None
    assert extract_known_product_name("") is None


def test_normalize_empty_input():
    assert normalize_product_name("") == ""


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
