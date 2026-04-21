from __future__ import annotations

from datetime import datetime
from time import mktime

import feedparser

from ..lib.jp_datetime import parse_jp_datetime
from ..lib.normalize import normalize_product_name
from ..lib.snapshot import content_hash
from ..lib.text_clean import clean_text
from .base import Candidate, SourceAdapter
from .http import fetch_text
from .registry import register_adapter

SHOPS = [
    ("megatokyo", "メガトウキョー"),
    ("shibuya", "シブヤ"),
    ("tokyobay", "トウキョーベイ"),
    ("tokyodx", "トウキョーDX"),
    ("skytreetown", "スカイツリータウン"),
    ("yokohama", "ヨコハマ"),
    ("nagoya", "ナゴヤ"),
    ("kyoto", "キョウト"),
    ("osaka", "オーサカ"),
    ("osakadx", "オーサカDX"),
    ("sapporo", "サッポロ"),
    ("tohoku", "トウホク"),
    ("fukuoka", "フクオカ"),
    ("hiroshima", "ヒロシマ"),
    ("kanazawa", "カナザワ"),
    ("kagawa", "カガワ"),
    ("okinawa", "オキナワ"),
]

_KEYWORDS = ("抽選", "販売方法", "再販", "入荷", "応募", "当選", "予約")


def _classify(title: str) -> str:
    if "抽選" in title:
        return "lottery"
    if "再販" in title or "入荷" in title:
        return "first_come"
    return "unknown"


@register_adapter("pokemoncenter_store_voice")
class PokecenStoreVoiceAdapter(SourceAdapter):
    """ポケセン各店舗の atom.xml を横断し、抽選/販売告知系エントリを抽出。"""

    def __init__(self, *, feeds: dict[str, str] | None = None) -> None:
        """feeds: shop_key -> xml 内容 のマップ。テスト用に差し替え可能。"""
        self._feeds = feeds

    async def run(self) -> list[Candidate]:
        out: list[Candidate] = []
        for shop_key, shop_display in SHOPS:
            try:
                if self._feeds is not None:
                    xml = self._feeds.get(shop_key)
                    if xml is None:
                        continue
                else:
                    xml = await fetch_text(
                        f"https://voice.pokemon.co.jp/stv/{shop_key}/atom.xml"
                    )
            except Exception:
                continue
            parsed = feedparser.parse(xml)
            for e in parsed.entries[:20]:
                title = (e.get("title") or "").strip()
                link = e.get("link") or ""
                if not title or not link:
                    continue
                if not any(k in title for k in _KEYWORDS):
                    continue
                ts = None
                if getattr(e, "published_parsed", None):
                    ts = datetime.fromtimestamp(mktime(e.published_parsed))
                sales_type = _classify(title)
                apply_dt = parse_jp_datetime(title)
                store_label = f"ポケモンセンター{shop_display}"
                out.append(Candidate(
                    product_name_raw=clean_text(title),
                    product_name_normalized=normalize_product_name(title),
                    retailer_name="pokemoncenter",
                    store_name=store_label,
                    sales_type=sales_type,
                    canonical_title=title,
                    apply_start_at=apply_dt,
                    source_name="pokemoncenter_store_voice",
                    source_url=link,
                    source_title=title,
                    source_published_at=ts,
                    raw_snapshot=content_hash(title + "|" + link),
                    extracted_payload={
                        "shop_key": shop_key,
                        "shop_display": shop_display,
                        "title": title,
                        "url": link,
                    },
                ))
        return out
