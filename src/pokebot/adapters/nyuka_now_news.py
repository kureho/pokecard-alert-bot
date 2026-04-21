from __future__ import annotations

import logging
import re
from datetime import datetime
from time import mktime

import feedparser

from ..lib.normalize import normalize_product_name
from ..lib.snapshot import content_hash
from ..lib.text_clean import clean_text
from ..lib.title_classifier import TitleCategory, classify_title
from .base import Candidate, SourceAdapter
from .http import fetch_text
from .registry import register_adapter

log = logging.getLogger(__name__)
FEED_URL = "https://nyuka-now.com/archives/category/news/feed"

_POKEMON_KEYWORDS = ("ポケモンカード", "ポケモンカードゲーム", "ポケカ", "ポケモン")

# タイトル先頭の 【4月20日(月)14時～】 パターン
_START_TIME_RE = re.compile(
    r"【(\d{1,2})月(\d{1,2})日\(?[月火水木金土日]\)?\s*(\d{1,2})時(?:～|〜|~)?】"
)

# Retailer キーワード
_RETAILER_MAP = [
    ("Amazon", "amazon"),
    ("アマゾン", "amazon"),
    ("ポケモンセンター", "pokemoncenter"),
    ("ポケセン", "pokemoncenter"),
    ("ヨドバシ", "yodobashi"),
    ("ビックカメラ", "biccamera"),
    ("あみあみ", "amiami"),
    ("Joshin", "joshin"),
    ("ジョーシン", "joshin"),
    ("ヤマダ", "yamada"),
    ("セブンネット", "seven_net"),
    ("楽天", "rakuten"),
]


def _detect_retailer(text: str) -> str:
    for kw, canon in _RETAILER_MAP:
        if kw in text:
            return canon
    return "nyuka_now"


def _parse_start_time(title: str, pub_year: int) -> datetime | None:
    m = _START_TIME_RE.search(title)
    if not m:
        return None
    month, day, hour = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return datetime(pub_year, month, day, hour, 0)
    except ValueError:
        return None


@register_adapter("nyuka_now_news")
class NyukaNowNewsAdapter(SourceAdapter):
    """nyuka-now.com /news/feed RSS。ポケモン関連の販売予定/発売予告を抽出。

    - 「【◯月◯日(曜)14時～】{商品名}の{販路}販売予定ページ」形式の tweets よりも
      固定的な News。apply_start_at を title から抽出 (publish year 基準)。
    """

    def __init__(self, *, xml: str | None = None) -> None:
        self._xml = xml

    async def run(self) -> list[Candidate]:
        xml = self._xml if self._xml is not None else await fetch_text(FEED_URL)
        parsed = feedparser.parse(xml)
        out: list[Candidate] = []
        for e in parsed.entries[:30]:
            title = (e.get("title") or "").strip()
            link = (e.get("link") or "").strip()
            if not title or not link:
                continue
            if not any(k in title for k in _POKEMON_KEYWORDS):
                continue

            analysis = classify_title(title)
            if analysis.category in (
                TitleCategory.LOTTERY_CLOSED,
                TitleCategory.LOTTERY_RESULT,
            ):
                continue

            ts = None
            year = datetime.now().year
            if getattr(e, "published_parsed", None):
                ts = datetime.fromtimestamp(mktime(e.published_parsed))
                year = ts.year

            sales_type = analysis.inferred_sales_type
            # keyword 推定
            if sales_type == "unknown":
                if "抽選" in title:
                    sales_type = "lottery"
                elif "招待" in title:
                    sales_type = "invitation"
                elif "先着" in title or "販売予定" in title:
                    sales_type = "first_come"

            # 【月日時～】から apply_start を抽出
            apply_start = _parse_start_time(title, year)

            # 商品名: "ポケモンカードゲーム MEGA 拡張パック アビスアイ" 部分
            core_match = re.search(
                r"(ポケモンカード[^のA-Za-z]*(?:ゲーム)?\s*[^の]{0,60}?)の", title
            )
            if core_match:
                product_core = core_match.group(1).strip()
            else:
                product_core = title.split("の", 1)[0][:80]

            product_name_raw = clean_text(product_core)
            product_name_normalized = normalize_product_name(product_core)
            if not product_name_normalized or len(product_name_normalized) < 2:
                continue

            retailer = _detect_retailer(title)

            out.append(
                Candidate(
                    product_name_raw=product_name_raw,
                    product_name_normalized=product_name_normalized,
                    retailer_name=retailer,
                    sales_type=sales_type if sales_type != "unknown" else "first_come",
                    canonical_title=title,
                    apply_start_at=apply_start,
                    source_name="nyuka_now_news",
                    source_url=link,
                    source_title=title,
                    source_published_at=ts,
                    raw_snapshot=content_hash(title + "|" + link),
                    extracted_payload={"title": title, "url": link},
                )
            )
        return out
