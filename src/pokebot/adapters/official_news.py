from __future__ import annotations

import logging
import re
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..lib.body_extractor import extract_body_info
from ..lib.normalize import normalize_product_name
from ..lib.snapshot import content_hash
from ..lib.text_clean import clean_text
from ..lib.title_classifier import TitleCategory, classify_title
from .base import Candidate, SourceAdapter
from .http import fetch_text
from .registry import register_adapter

log = logging.getLogger(__name__)
BASE = "https://www.pokemon-card.com"

_DATE_DOT = re.compile(r"(\d{4})\.(\d{1,2})\.(\d{1,2})")


def _parse_post_date(a) -> datetime | None:
    span = a.select_one(".Date, .Date-small, span.Date")
    if not span:
        return None
    m = _DATE_DOT.search(span.get_text())
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


@register_adapter("pokemon_official_news")
class PokemonOfficialNewsAdapter(SourceAdapter):
    url = f"{BASE}/info/"

    def __init__(
        self,
        *,
        html: str | None = None,
        body_fetcher=None,
        max_body_fetch: int = 20,
    ) -> None:
        """html: テスト注入用。body_fetcher: 個別記事 html 取得。Noneなら fetch_text 使用。"""
        self._html = html
        self._body_fetcher = body_fetcher
        self._max_body_fetch = max_body_fetch

    async def run(self) -> list[Candidate]:
        html = self._html if self._html is not None else await fetch_text(self.url)
        soup = BeautifulSoup(html, "html.parser")
        candidates: list[Candidate] = []
        fetched = 0
        for a in soup.select("li.List_item a.List_item_inner[href]"):
            href = a.get("href") or ""
            img = a.select_one(".List_title img[alt]")
            title = (img.get("alt") or "").strip() if img else ""
            if not title:
                body = a.select_one(".List_body")
                if body:
                    for el in body.select(".Calendar_Label, .Date"):
                        el.extract()
                    title = body.get_text(strip=True)
            if not title or not href:
                continue

            analysis = classify_title(title)
            # 候補化しない分類
            if analysis.category in (
                TitleCategory.IRRELEVANT,
                TitleCategory.LOTTERY_CLOSED,
                TitleCategory.LOTTERY_RESULT,
            ):
                continue
            # 発売告知のみは本文 fetch で抽選情報の有無を確認してから決定
            need_body = analysis.category in (
                TitleCategory.LOTTERY_ACTIVE,
                TitleCategory.FIRST_COME_ACTIVE,
                TitleCategory.SALES_METHOD,
                TitleCategory.RELEASE_ANNOUNCE,
            )

            url = urljoin(BASE, href)
            post_date = _parse_post_date(a)

            # 商品名正規化
            product_name_raw = clean_text(title)
            product_name_normalized = normalize_product_name(title)

            # 本文 fetch (per-run 制限)
            body_info = None
            body_html = None
            if need_body and fetched < self._max_body_fetch:
                try:
                    body_html = (
                        await self._body_fetcher(url) if self._body_fetcher
                        else await fetch_text(url)
                    )
                    body_info = extract_body_info(body_html)
                    fetched += 1
                except Exception as e:  # noqa: BLE001
                    log.warning("body fetch failed for %s: %s", url, e)

            # 発売告知のみで本文に応募情報が無ければ skip
            if analysis.category == TitleCategory.RELEASE_ANNOUNCE:
                if body_info is None or not body_info.has_any_date:
                    continue

            # 日付は本文優先、無ければ None (タイトル日付は発売日の可能性が高いので避ける)
            apply_start = body_info.apply_start_at if body_info else None
            apply_end = body_info.apply_end_at if body_info else None
            result_at = body_info.result_at if body_info else None
            purchase_start = body_info.purchase_start_at if body_info else None
            purchase_end = body_info.purchase_end_at if body_info else None
            purchase_limit = body_info.purchase_limit_text if body_info else None
            conditions = body_info.conditions_text if body_info else None

            snapshot_src = body_html if body_html else (title + "|" + url)

            candidates.append(Candidate(
                product_name_raw=product_name_raw,
                product_name_normalized=product_name_normalized,
                retailer_name="pokemoncenter_online",
                sales_type=analysis.inferred_sales_type,
                canonical_title=title,
                apply_start_at=apply_start,
                apply_end_at=apply_end,
                result_at=result_at,
                purchase_start_at=purchase_start,
                purchase_end_at=purchase_end,
                purchase_limit_text=purchase_limit,
                conditions_text=conditions,
                source_name="pokemon_official_news",
                source_url=url,
                source_title=title,
                source_published_at=post_date,
                raw_snapshot=content_hash(snapshot_src),
                extracted_payload={
                    "title": title,
                    "url": url,
                    "title_category": str(analysis.category),
                    "body_fetched": body_info is not None,
                    "body_score": body_info.score if body_info else 0,
                },
            ))
        return candidates
