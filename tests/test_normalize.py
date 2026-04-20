from datetime import date

import pytest
from pokebot.normalize import normalize_title


@pytest.mark.parametrize(
    "raw,expected_name,expected_category",
    [
        (
            "ポケモンカードゲーム 拡張パック「テラスタルフェスex」BOX",
            "テラスタルフェスex",
            "拡張パック",
        ),
        (
            "【抽選販売】拡張パック　テラスタルフェスex　ボックス",
            "テラスタルフェスex",
            "拡張パック",
        ),
        ("強化拡張パック ポケモンカード151 Box", "ポケモンカード151", "強化拡張パック"),
        (
            "ハイクラスパック シャイニートレジャーex BOX",
            "シャイニートレジャーex",
            "ハイクラスパック",
        ),
    ],
)
def test_normalize_extracts_name_and_category(raw, expected_name, expected_category):
    n = normalize_title(raw)
    assert n.product_name == expected_name
    assert n.category == expected_category
    assert n.is_box is True


def test_normalize_non_box_returns_is_box_false():
    n = normalize_title("拡張パック テラスタルフェスex 1パック")
    assert n.is_box is False


def test_normalize_handles_hankaku_brackets():
    n = normalize_title("[抽選] 拡張パック テラスタルフェスex BOX")
    assert n.product_name == "テラスタルフェスex"


def test_normalized_key_stable():
    n = normalize_title("拡張パック「テラスタルフェスex」BOX")
    k1 = n.key(release_date=date(2026, 3, 14))
    k2 = n.key(release_date=date(2026, 3, 14))
    assert k1 == k2
    assert "テラスタルフェスex" in k1
    assert "2026-03-14" in k1


def test_normalized_key_fallback_to_url_hash():
    n = normalize_title("拡張パック テラスタルフェスex BOX")
    k = n.key(url="https://www.yodobashi.com/product/12345")
    assert k.endswith("BOX")
    assert "uid=" in k
