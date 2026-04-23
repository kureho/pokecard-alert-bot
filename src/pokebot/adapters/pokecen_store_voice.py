from __future__ import annotations

import logging
from datetime import datetime
from time import mktime

import feedparser

from ..lib.body_extractor import extract_body_info
from ..lib.normalize import normalize_product_name
from ..lib.region import is_pokecen_tokyo_metro
from ..lib.snapshot import content_hash
from ..lib.text_clean import clean_text
from ..lib.title_classifier import TitleCategory, classify_title
from .base import Candidate, SourceAdapter
from .http import fetch_text
from .registry import register_adapter

log = logging.getLogger(__name__)

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


@register_adapter("pokemoncenter_store_voice")
class PokecenStoreVoiceAdapter(SourceAdapter):
    """ポケセン各店舗の atom.xml を横断し、抽選/販売告知系エントリを抽出。"""

    def __init__(
        self,
        *,
        feeds: dict[str, str] | None = None,
        body_fetcher=None,
        max_body_fetch: int = 30,
    ) -> None:
        """feeds: shop_key -> xml 内容 のマップ。テスト用に差し替え可能。
        body_fetcher: 個別記事 html 取得。Noneなら fetch_text 使用。
        """
        self._feeds = feeds
        self._body_fetcher = body_fetcher
        self._max_body_fetch = max_body_fetch

    async def run(self) -> list[Candidate]:
        out: list[Candidate] = []
        fetched = 0
        for shop_key, shop_display in SHOPS:
            # 東京近郊 (1都3県) 以外の店舗は feed 取得もしない。
            if not is_pokecen_tokyo_metro(shop_key):
                continue
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

                analysis = classify_title(title)
                if analysis.category in (
                    TitleCategory.IRRELEVANT,
                    TitleCategory.LOTTERY_CLOSED,
                    TitleCategory.LOTTERY_RESULT,
                ):
                    continue

                ts = None
                if getattr(e, "published_parsed", None):
                    ts = datetime.fromtimestamp(mktime(e.published_parsed))

                body_info = None
                body_html = None
                if fetched < self._max_body_fetch:
                    try:
                        body_html = (
                            await self._body_fetcher(link) if self._body_fetcher
                            else await fetch_text(link)
                        )
                        body_info = extract_body_info(body_html)
                        fetched += 1
                    except Exception as ex:  # noqa: BLE001
                        log.warning(
                            "store_voice body fetch failed for %s: %s", link, ex
                        )

                # 発売告知のみで本文に応募情報が無ければ skip
                if analysis.category == TitleCategory.RELEASE_ANNOUNCE:
                    if body_info is None or not body_info.has_any_date:
                        continue

                # sales_type 確定: title 由来を基本に、title が unknown の場合は body から推定。
                # これにより「販売方法について」(SALES_METHOD) で title 判別不能だった記事も、
                # 本文に「抽選」「先着」等があれば正しく sales_type を決められる。
                sales_type = analysis.inferred_sales_type
                if sales_type == "unknown" and body_info:
                    sales_type = body_info.inferred_sales_type

                # title も body も sales_type 判別不能なら DB に入れない (ノイズ排除)。
                # pending_review で溜まり続けて通知に繋がらない event を生成しない。
                if sales_type == "unknown":
                    continue

                # 商品名: body の h1/title を優先 (タイトル【】等ノイズ除去のため)
                if body_info and body_info.product_name:
                    product_name_raw = clean_text(body_info.product_name)
                    product_name_normalized = normalize_product_name(body_info.product_name)
                else:
                    product_name_raw = clean_text(title)
                    product_name_normalized = normalize_product_name(title)

                apply_start = body_info.apply_start_at if body_info else None
                apply_end = body_info.apply_end_at if body_info else None
                result_at = body_info.result_at if body_info else None
                purchase_start = body_info.purchase_start_at if body_info else None
                purchase_end = body_info.purchase_end_at if body_info else None
                purchase_limit = body_info.purchase_limit_text if body_info else None
                conditions = body_info.conditions_text if body_info else None

                store_label = f"ポケモンセンター{shop_display}"
                snapshot_src = body_html if body_html else (title + "|" + link)

                out.append(Candidate(
                    product_name_raw=product_name_raw,
                    product_name_normalized=product_name_normalized,
                    retailer_name="pokemoncenter",
                    store_name=store_label,
                    sales_type=sales_type,
                    canonical_title=title,
                    apply_start_at=apply_start,
                    apply_end_at=apply_end,
                    result_at=result_at,
                    purchase_start_at=purchase_start,
                    purchase_end_at=purchase_end,
                    purchase_limit_text=purchase_limit,
                    conditions_text=conditions,
                    source_name="pokemoncenter_store_voice",
                    source_url=link,
                    source_title=title,
                    source_published_at=ts,
                    raw_snapshot=content_hash(snapshot_src),
                    extracted_payload={
                        "shop_key": shop_key,
                        "shop_display": shop_display,
                        "title": title,
                        "url": link,
                        "title_category": str(analysis.category),
                        "body_fetched": body_info is not None,
                        "body_score": body_info.score if body_info else 0,
                    },
                    evidence_type="store_notice",
                    application_url=link,
                ))
        return out
