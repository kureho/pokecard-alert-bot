from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..lib.normalize import normalize_product_name
from ..lib.snapshot import content_hash
from ..lib.text_clean import clean_text
from ..lib.title_classifier import TitleCategory, classify_title
from .base import Candidate, SourceAdapter
from .http import fetch_text
from .registry import register_adapter

log = logging.getLogger(__name__)
BASE = "https://www.c-labo.jp"
URL = f"{BASE}/blog/"

# shop slug を店舗名に再マッピング (unknown はそのまま slug を使う)
_SHOP_DISPLAY = {
    "akihabara": "カードラボ秋葉原",
    "stakihabara": "カードラボ秋葉原2号店",
    "shinjuku": "カードラボ新宿",
    "ikebukuro": "カードラボ池袋",
    "shibuya": "カードラボ渋谷",
    "yokohama": "カードラボ横浜",
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
    """カードラボ 店舗ブログ。ポケカ関連の抽選/再販告知を横断抽出。"""

    def __init__(self, *, html: str | None = None) -> None:
        self._html = html

    async def run(self) -> list[Candidate]:
        html = self._html if self._html is not None else await fetch_text(URL)
        soup = BeautifulSoup(html, "html.parser")
        out: list[Candidate] = []

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

            # blog list には日付がないので記事ページ fetch が望ましいが、
            # Phase 1 では list 情報のみで candidate 化する。
            # source_published_at=None → confidence でペナルティ → confirmed に届かない可能性高
            sales_type = analysis.inferred_sales_type
            if sales_type == "unknown":
                sales_type = "lottery"

            out.append(
                Candidate(
                    product_name_raw=clean_text(core),
                    product_name_normalized=product_name_normalized,
                    retailer_name="cardlabo",
                    store_name=store_display,
                    sales_type=sales_type,
                    canonical_title=title,
                    source_name="c_labo_blog",
                    source_url=url,
                    source_title=title,
                    raw_snapshot=content_hash(title + "|" + url),
                    extracted_payload={
                        "shop_slug": shop_slug,
                        "title": title,
                        "url": url,
                        "title_category": str(analysis.category),
                    },
                )
            )
        return out
