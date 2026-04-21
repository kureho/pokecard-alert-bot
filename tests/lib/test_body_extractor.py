from pokebot.lib.body_extractor import extract_body_info


def test_extracts_apply_period():
    html = """<html><body>
    <h1>アビスアイ抽選販売</h1>
    <p>応募期間: 2026年5月10日(土) 14:00 〜 2026年5月14日(水) 23:59</p>
    <p>結果発表: 2026年5月16日(金) 11:00</p>
    <p>購入期間: 2026年5月20日(火) 10:00 〜 2026年5月22日(木) 23:59</p>
    <p>お一人様 1点まで</p>
    </body></html>"""
    r = extract_body_info(html)
    assert r.apply_start_at is not None
    assert r.apply_end_at is not None
    assert r.result_at is not None
    assert r.apply_start_at.month == 5 and r.apply_start_at.day == 10
    assert r.apply_end_at.day == 14
    assert r.result_at.day == 16
    assert r.has_any_date
    assert r.conditions_text is not None


def test_release_page_without_lottery_info_has_no_dates():
    html = """<html><body>
    <h1>アビスアイ発売</h1>
    <p>発売日: 5月22日</p>
    </body></html>"""
    r = extract_body_info(html)
    assert not r.has_any_date


def test_alternative_label_applies():
    html = "<p>抽選応募期間: 4月20日 10:00 〜 4月25日 18:00</p>"
    r = extract_body_info(html)
    assert r.apply_start_at is not None
    assert r.apply_end_at is not None


def test_extracts_product_name_from_h1():
    html = """<html><head><title>アビスアイ｜ポケモンセンター</title></head>
    <body><h1>拡張パック アビスアイ</h1><p>本文</p></body></html>"""
    r = extract_body_info(html)
    assert r.product_name == "拡張パック アビスアイ"


def test_extracts_product_name_from_title_if_no_h1():
    html = """<html><head><title>アビスアイ抽選｜ポケモンカード公式</title></head>
    <body><p>本文のみ</p></body></html>"""
    r = extract_body_info(html)
    assert r.product_name == "アビスアイ抽選"


def test_product_name_none_if_neither():
    html = """<html><body><p>title も h1 も無いページ</p></body></html>"""
    r = extract_body_info(html)
    assert r.product_name is None
