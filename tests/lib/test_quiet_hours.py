"""quiet hours (通知抑止時間帯) の境界判定を検証。"""

from datetime import datetime

from pokebot.lib.quiet_hours import is_quiet_hours


def test_morning_boundary_10_00_is_allowed():
    """10:00 ちょうどは送信再開 (ユーザー要望「朝10時まで送らない」)。"""
    assert is_quiet_hours(datetime(2026, 4, 22, 10, 0)) is False
    assert is_quiet_hours(datetime(2026, 4, 22, 10, 0, 1)) is False
    # 9:59 は抑止中
    assert is_quiet_hours(datetime(2026, 4, 22, 9, 59)) is True


def test_night_boundary_21_00_is_suppressed():
    """21:00 から抑止開始。"""
    assert is_quiet_hours(datetime(2026, 4, 22, 20, 59)) is False
    assert is_quiet_hours(datetime(2026, 4, 22, 21, 0)) is True
    assert is_quiet_hours(datetime(2026, 4, 22, 21, 30)) is True


def test_midnight_and_early_morning_are_suppressed():
    """深夜〜早朝は抑止中。"""
    for h in (0, 1, 2, 3, 4, 5, 6, 7, 8, 9):
        assert is_quiet_hours(datetime(2026, 4, 22, h, 0)) is True, f"hour={h}"


def test_daytime_is_allowed():
    """日中 (10:00-20:59) は送信可。"""
    for h in range(10, 21):
        assert is_quiet_hours(datetime(2026, 4, 22, h, 0)) is False, f"hour={h}"
