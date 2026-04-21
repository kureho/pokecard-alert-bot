import pytest

from pokebot.lib.title_classifier import TitleCategory, classify_title


@pytest.mark.parametrize("title,expected_category", [
    ("【ポケモンセンターメガトウキョー】3月13日（金）抽選販売商品 当選者へのお知らせ",
     TitleCategory.LOTTERY_RESULT),
    ("【ポケモンセンターシブヤ】1月23日（金）～24日（土）抽選販売商品 当選者へのお知らせ",
     TitleCategory.LOTTERY_RESULT),
    ("3月13日（金）発売のポケモンカードゲーム関連商品の販売方法について",
     TitleCategory.SALES_METHOD),
    ("拡張パック「アビスアイ」が、5月22日(金)に発売!",
     TitleCategory.RELEASE_ANNOUNCE),
    ("ポケモンカードゲーム 30周年記念商品 世界同時発売決定!",
     TitleCategory.RELEASE_ANNOUNCE),
    ("追加先着エントリーの受付開始",
     TitleCategory.FIRST_COME_ACTIVE),
    ("アビスアイ 抽選応募受付開始のお知らせ",
     TitleCategory.LOTTERY_ACTIVE),
    ("4月18日（土）『ポケモン GO』部門ポケモンセンター予選大会のお知らせ",
     TitleCategory.IRRELEVANT),
    ("「チャンピオンズリーグ2026 愛知 May」ジュニアリーグ2日目大会の追加エントリーについて",
     TitleCategory.IRRELEVANT),
])
def test_classify(title, expected_category):
    assert classify_title(title).category == expected_category


def test_lottery_active_sales_type():
    assert classify_title("アビスアイ 抽選応募受付開始のお知らせ").inferred_sales_type == "lottery"


def test_first_come_sales_type():
    assert classify_title("追加先着エントリーの受付開始").inferred_sales_type == "first_come"


def test_preorder_lottery_detected():
    analysis = classify_title("抽選予約開始のお知らせ")
    assert analysis.category == TitleCategory.LOTTERY_ACTIVE
    assert analysis.inferred_sales_type == "preorder_lottery"
