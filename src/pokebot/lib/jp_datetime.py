from __future__ import annotations

import re
import unicodedata
from datetime import datetime

_MONTH_DAY = re.compile(r"(\d{1,2})月(\d{1,2})日")
_HOUR_MIN = re.compile(r"(\d{1,2})[:：](\d{1,2})")
_HOUR_ONLY = re.compile(r"(\d{1,2})時(?:(\d{1,2})分)?")
_YEAR = re.compile(r"(20\d{2})年")


def parse_jp_datetime(text: str, *, default_year: int | None = None) -> datetime | None:
    """日本語の日時表現をできるだけ拾う。例:
    - '2026年5月22日（金）14:00'
    - '5月10日 14:00'
    - '5月14日 23:59まで'
    - '4月20日(月)10:00'
    Returns naive datetime (no tz).
    """
    if not text:
        return None
    s = unicodedata.normalize("NFKC", text)
    md = _MONTH_DAY.search(s)
    if not md:
        return None
    month, day = int(md.group(1)), int(md.group(2))
    year = default_year or datetime.now().year
    ym = _YEAR.search(s)
    if ym:
        year = int(ym.group(1))
    hour, minute = 0, 0
    hm = _HOUR_MIN.search(s)
    if hm:
        hour, minute = int(hm.group(1)), int(hm.group(2))
    else:
        ho = _HOUR_ONLY.search(s)
        if ho:
            hour = int(ho.group(1))
            if ho.group(2):
                minute = int(ho.group(2))
    try:
        return datetime(year, month, day, hour, minute)
    except ValueError:
        return None
