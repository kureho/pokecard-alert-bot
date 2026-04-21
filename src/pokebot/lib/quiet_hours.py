"""通知を送らない時間帯 (JST) の判定。

ユーザーの睡眠時間を守るため、21:00 〜 翌 10:00 は LINE 送信を抑止する。
全ての LINE 経路 (new / update / deadline / daily_summary / silence) で共通適用。

時刻は datetime.now() の hour を基準にする。GHA workflow は TZ=Asia/Tokyo
なので、datetime.now() は JST の naive datetime となる (schema/ テストも同様)。
UTC の runner で直接 datetime.utcnow() を使うとズレる点に注意。
"""

from __future__ import annotations

from datetime import datetime

# 21:00 <= hour < 10:00 (翌朝) の間は送信抑止。
# 21:00 から含み、10:00 の頭から送信再開 (ユーザー要望「朝10時まで送らない」)。
QUIET_HOURS_START_HOUR = 21
QUIET_HOURS_END_HOUR = 10


def is_quiet_hours(now: datetime) -> bool:
    """now が「通知を送らない時間帯」か。

    判定は hour フィールドだけを見る (分秒は無視)。境界は以下:
    - 20:59 → False (送信可)
    - 21:00 → True  (抑止開始)
    - 23:59, 00:00, 09:59 → True (抑止中)
    - 10:00 → False (送信再開)
    """
    h = now.hour
    return h >= QUIET_HOURS_START_HOUR or h < QUIET_HOURS_END_HOUR
