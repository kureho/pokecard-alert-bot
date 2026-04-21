from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..lib.body_extractor import extract_body_info
from ..lib.normalize import normalize_product_name
from ..lib.region import is_clabo_tokyo_metro
from ..lib.snapshot import content_hash
from ..lib.text_clean import clean_text
from ..lib.title_classifier import TitleCategory, classify_title
from .base import Candidate, SourceAdapter
from .http import fetch_text
from .registry import register_adapter

log = logging.getLogger(__name__)
BASE = "https://www.c-labo.jp"
URL = f"{BASE}/blog/"

# shop slug を店舗名に再マッピング。region.py の Tokyo-metro allowlist と
# 1都3県分は必ず一致させること (フォールバック名で通知されないように)。
_SHOP_DISPLAY = {
    # 東京都
    "akihabara": "カードラボ秋葉原",
    "stakihabara": "カードラボ秋葉原2号店",
    "shinjuku": "カードラボ新宿",
    "ikebukuro": "カードラボ池袋",
    "shibuya": "カードラボ渋谷",
    # 神奈川
    "yokohama": "カードラボ横浜",
    # 埼玉
    "tokorozawa": "カードラボ所沢",
    # 千葉
    "tsudanuma": "カードラボ津田沼",
    # 以下は allowlist 外 (通知対象外)。将来 allowlist を広げた場合の display 用に残す。
    "nagoya": "カードラボ名古屋",
    "nagoyaekimae": "カードラボ名古屋駅前",
    "nagoyaoosu": "カードラボ名古屋大須",
    "hamamatsu": "カードラボ浜松",
    "shizuoka": "カードラボ静岡",
    "kyoto": "カードラボ京都",
    "osaka": "カードラボ大阪",
    "namba": "カードラボなんば",
    "nipponbashi": "カードラボ日本橋",
    "tennouji": "カードラボ天王寺",
    "kobe": "カードラボ神戸",
    "hiroshima": "カードラボ広島",
    "fukuoka": "カードラボ福岡",
    "gifu": "カードラボ岐阜",
    "sendai": "カードラボ仙台",
    "sapporo": "カードラボ札幌",
    "otaro": "カードラボ小樽",
}

_POKEMON_KEYWORDS = ("ポケモンカード", "ポケモンカードゲーム", "ポケカ")
_SHOP_PATH_RE = re.compile(r"/shop/([^/]+)/blog/")


def _extract_shop(href: str) -> tuple[str, str]:
    m = _SHOP_PATH_RE.search(href)
    if not m:
        return "unknown", "カードラボ"
    slug = m.group(1)
    return slug, _SHOP_DISPLAY.get(slug, f"カードラボ({slug})")


@register_adapter("c_labo_blog")
class CLaboBlogAdapter(SourceAdapter):
    """カードラボ 店舗ブログ。ポケカ関連の抽選/再販告知を横断抽出。

    list ページの a.js-targetLink から候補を拾い、各記事本文を fetch して
    「応募期間」「結果発表」「購入期間」などを抽出する。
    本文 fetch は per-run で上限を設け、過剰な GET を避ける。
    """

    def __init__(
        self,
        *,
        html: str | None = None,
        body_fetcher=None,
        max_body_fetch: int = 15,
    ) -> None:
        self._html = html
        self._body_fetcher = body_fetcher
        self._max_body_fetch = max_body_fetch

    async def run(self) -> list[Candidate]:
        html = self._html if self._html is not None else await fetch_text(URL)
        soup = BeautifulSoup(html, "html.parser")
        out: list[Candidate] = []
        fetched = 0

        # .claboCard > .js-targetLink (title 属性に記事タイトル、href に URL)
        for a in soup.select("a.js-targetLink[href]"):
            href = a.get("href") or ""
            title = (a.get("title") or a.get_text(strip=True)).strip()
            if not title or not href:
                continue
            if not any(k in title for k in _POKEMON_KEYWORDS):
                continue

            analysis = classify_title(title)
            # 過去イベントは確実に除外。
            if analysis.category in (
                TitleCategory.LOTTERY_CLOSED,
                TitleCategory.LOTTERY_RESULT,
            ):
                continue
            # IRRELEVANT でも「抽選」「販売」キーワードが無ければ skip
            # (大会告知・プレゼントキャンペーン等を除外)
            if analysis.category == TitleCategory.IRRELEVANT:
                if "抽選" not in title and "販売" not in title and "予約" not in title:
                    continue

            shop_slug, store_display = _extract_shop(href)
            # 東京近郊 (1都3県) 以外の店舗は通知対象外。body fetch もしない。
            if not is_clabo_tokyo_metro(shop_slug):
                continue
            url = urljoin(BASE, href)

            # 商品名抽出: title から「抽選販売のお知らせ」「抽選予約販売のお知らせ」等を削除
            core = title
            for suffix in (
                "抽選予約・販売のお知らせ",
                "抽選予約販売のお知らせ",
                "抽選販売のお知らせ",
                "抽選予約のお知らせ",
                "抽選販売について",
                "販売のお知らせ",
            ):
                core = core.replace(suffix, "")
            # 「【◯月◯日発売】」prefix 除去
            core = re.sub(r"^【[^】]+】\s*", "", core)
            core = clean_text(core)

            product_name_normalized = normalize_product_name(core)
            if not product_name_normalized or len(product_name_normalized) < 2:
                continue

            sales_type = analysis.inferred_sales_type
            if sales_type == "unknown":
                sales_type = "lottery"

            # 記事本文 fetch (per-run cap あり)
            body_info = None
            body_html = None
            if fetched < self._max_body_fetch:
                try:
                    body_html = (
                        await self._body_fetcher(url)
                        if self._body_fetcher
                        else await fetch_text(url)
                    )
                    body_info = extract_body_info(body_html)
                    fetched += 1
                except Exception as e:  # noqa: BLE001
                    log.warning("c_labo body fetch failed for %s: %s", url, e)

            # 本文から dates 抽出
            apply_start = body_info.apply_start_at if body_info else None
            apply_end = body_info.apply_end_at if body_info else None
            result_at = body_info.result_at if body_info else None
            purchase_start = body_info.purchase_start_at if body_info else None
            purchase_end = body_info.purchase_end_at if body_info else None
            purchase_limit = body_info.purchase_limit_text if body_info else None
            conditions = body_info.conditions_text if body_info else None

            # 商品名: body h1/title があればそちらを優先
            if body_info and body_info.product_name:
                prod_from_body = normalize_product_name(body_info.product_name)
                if prod_from_body and len(prod_from_body) >= 2:
                    product_name_normalized = prod_from_body
                    core = clean_text(body_info.product_name)

            snapshot_src = body_html if body_html else (title + "|" + url)

            out.append(
                Candidate(
                    product_name_raw=clean_text(core),
                    product_name_normalized=product_name_normalized,
                    retailer_name="cardlabo",
                    store_name=store_display,
                    sales_type=sales_type,
                    canonical_title=title,
                    apply_start_at=apply_start,
                    apply_end_at=apply_end,
                    result_at=result_at,
                    purchase_start_at=purchase_start,
                    purchase_end_at=purchase_end,
                    purchase_limit_text=purchase_limit,
                    conditions_text=conditions,
                    source_name="c_labo_blog",
                    source_url=url,
                    source_title=title,
                    raw_snapshot=content_hash(snapshot_src),
                    extracted_payload={
                        "shop_slug": shop_slug,
                        "title": title,
                        "url": url,
                        "title_category": str(analysis.category),
                        "body_fetched": body_info is not None,
                        "body_score": body_info.score if body_info else 0,
                    },
                    evidence_type="store_notice",
                    application_url=url,
                )
            )
        return out
