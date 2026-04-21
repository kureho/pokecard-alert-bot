from datetime import datetime
from pokebot.lib.jp_datetime import parse_jp_datetime


def test_parses_full():
    assert parse_jp_datetime("2026年5月22日（金）14:00") == datetime(2026, 5, 22, 14, 0)


def test_parses_wareki_less_year():
    # no year specified → default_year 既定
    assert parse_jp_datetime("5月10日 14:00", default_year=2026) == datetime(2026, 5, 10, 14, 0)


def test_parses_hour_only():
    assert parse_jp_datetime("4月20日(月)10時", default_year=2026) == datetime(2026, 4, 20, 10, 0)


def test_parses_end_marker():
    assert parse_jp_datetime("応募期間: 5月14日 23:59まで", default_year=2026) == datetime(2026, 5, 14, 23, 59)


def test_returns_none_on_no_date():
    assert parse_jp_datetime("") is None
    assert parse_jp_datetime("抽選販売です") is None
