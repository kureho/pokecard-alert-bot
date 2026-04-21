"""ホビーステーション (hbst.net) ポケカ抽選告知 RSS adapter。

hbst.net は WordPress 運用で、ポケカ抽選情報を記事として投稿している。
RSS feed (/feed/) に最新記事が流れるため、タイトルフィルタで抽出。

タイトル例: 「【2026.04.17】※応募は終了しました抽選販売「ポケモンカードゲームMEGA ハイクラスパック メガドリームex（再販）」」
本文には ■応募期間 / ■当選発表 / ■当選者購入期間 が定型で記載される。
本文内の Livepocket URL は application_url として採用。

evidence_type: store_notice (ホビーステーション公式告知)
entry_method: web_form (Livepocket 経由)
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from time import mktime

import feedparser

from ..lib.body_extractor import extract_body_info
from ..lib.normalize import normalize_product_name
from ..lib.snapshot import content_hash
from ..lib.text_clean import clean_text
from .base import Candidate, SourceAdapter
from .http import fetch_text
from .registry import register_adapter

log = logging.getLogger(__name__)
FEED_URL = "https://www.hbst.net/feed/"

_POKEMON_KEYWORDS = ("ポケモンカード", "ポケモンカードゲーム", "ポケカ")

# 「【YYYY.MM.DD】※...」prefix を除去
_TITLE_DATE_PREFIX_RE = re.compile(r"^【\d{4}[./]\d{1,2}[./]\d{1,2}】\s*")
# 「※応募は終了しました」「※当選発表」等の注記を除去
_TITLE_NOTE_RE = re.compile(r"※[^「『]{2,30}")
# 「抽選販売」「抽選予約」suffix (商品名の前にある)
_TITLE_SUFFIX_TYPE_RE = re.compile(r"^(?:抽選販売|抽選予約販売|抽選予約|販売)")
# 「」『』 で囲まれた部分を商品名として拾う
_QUOTED_NAME_RE = re.compile(r"[「『]([^」』]+)[」』]")
# Livepocket URL
_LIVEPOCKET_RE = re.compile(r"https?://(?:livepocket\.jp|l-tike\.com)/[A-Za-z0-9/_\-]+")


def _extract_product_name(title: str) -> str:
    """hbst のタイトル形式から商品名を取り出す。"""
    s = _TITLE_DATE_PREFIX_RE.sub("", title)
    s = _TITLE_NOTE_RE.sub("", s)
    s = _TITLE_SUFFIX_TYPE_RE.sub("", s)
    m = _QUOTED_NAME_RE.search(s)
    if m:
        return clean_text(m.group(1))
    return clean_text(s)


def _detect_sale_status(title: str, body_text: str) -> str:
    if "応募は終了" in title or "応募は終了" in body_text:
        return "ended"
    if "当選発表" in body_text and "応募期間" in body_text:
        return "accepting"
    return "unknown"


def _extract_application_url(body_text: str, body_html: str) -> str | None:
    # プレーンテキストから先に試す (clean_text 後の body_text 想定)
    m = _LIVEPOCKET_RE.search(body_text)
    if m:
        return m.group(0)
    m = _LIVEPOCKET_RE.search(body_html)
    if m:
        return m.group(0)
    return None


@register_adapter("hbst_lottery")
class HbstLotteryAdapter(SourceAdapter):
    """ホビーステーション RSS 抽選告知。

    RSS 最新 20 件からポケカキーワードを含む記事を抽出し、各本文を fetch。
    per-run で本文 fetch 数に上限を設けて負荷を抑える。
    """

    def __init__(
        self,
        *,
        xml: str | None = None,
        body_fetcher=None,
        max_body_fetch: int = 8,
    ) -> None:
        self._xml = xml
        self._body_fetcher = body_fetcher
        self._max_body_fetch = max_body_fetch

    async def run(self) -> list[Candidate]:
        xml = self._xml if self._xml is not None else await fetch_text(FEED_URL)
        parsed = feedparser.parse(xml)
        out: list[Candidate] = []
        fetched = 0
        for e in parsed.entries[:20]:
            title = (e.get("title") or "").strip()
            link = (e.get("link") or "").split("?")[0]
            if not title or not link:
                continue
            if not any(k in title for k in _POKEMON_KEYWORDS):
                continue
            # 「抽選販売」「抽選予約」を含まないポケモン関連投稿はスキップ
            if not any(
                k in title for k in ("抽選販売", "抽選予約", "抽選受付", "抽選")
            ):
                continue

            product_name_raw = _extract_product_name(title)
            product_name_normalized = normalize_product_name(product_name_raw)
            if not product_name_normalized or len(product_name_normalized) < 2:
                continue

            ts = None
            if getattr(e, "published_parsed", None):
                ts = datetime.fromtimestamp(mktime(e.published_parsed))

            body_info = None
            body_html = None
            app_url = None
            if fetched < self._max_body_fetch:
                try:
                    body_html = (
                        await self._body_fetcher(link)
                        if self._body_fetcher
                        else await fetch_text(link)
                    )
                    body_info = extract_body_info(body_html)
                    fetched += 1
                    app_url = _extract_application_url(body_info.body_text, body_html)
                except Exception as exc:  # noqa: BLE001
                    log.warning("hbst body fetch failed for %s: %s", link, exc)

            apply_start = body_info.apply_start_at if body_info else None
            apply_end = body_info.apply_end_at if body_info else None
            result_at = body_info.result_at if body_info else None
            purchase_start = body_info.purchase_start_at if body_info else None
            purchase_end = body_info.purchase_end_at if body_info else None
            purchase_limit = body_info.purchase_limit_text if body_info else None
            conditions = body_info.conditions_text if body_info else None

            sale_status = _detect_sale_status(
                title, body_info.body_text if body_info else ""
            )

            # body の product_name が取れればそちらを優先
            if body_info and body_info.product_name:
                # タイトルから取った商品名より body title の方が正確なことが多い
                body_product_title = body_info.product_name
                # body_info.product_name は「【...】※... -」を含むので再抽出
                body_product = _extract_product_name(body_product_title)
                prod_norm = normalize_product_name(body_product)
                if prod_norm and len(prod_norm) >= 2:
                    product_name_normalized = prod_norm
                    product_name_raw = body_product

            snapshot_src = body_html if body_html else (title + "|" + link)

            # 応募情報が何も取れず終了もしていない場合はスキップ
            if (
                body_info is not None
                and not body_info.has_any_date
                and sale_status != "ended"
            ):
                continue

            out.append(
                Candidate(
                    product_name_raw=product_name_raw,
                    product_name_normalized=product_name_normalized,
                    retailer_name="hobby_station",
                    sales_type="lottery",
                    canonical_title=title,
                    apply_start_at=apply_start,
                    apply_end_at=apply_end,
                    result_at=result_at,
                    purchase_start_at=purchase_start,
                    purchase_end_at=purchase_end,
                    purchase_limit_text=purchase_limit,
                    conditions_text=conditions,
                    source_name="hbst_lottery",
                    source_url=link,
                    source_title=title,
                    source_published_at=ts,
                    raw_snapshot=content_hash(snapshot_src),
                    application_url=app_url or link,
                    entry_method="web_form" if app_url else "unknown",
                    sale_status_hint=sale_status,
                    evidence_type="store_notice",
                    raw_text_excerpt=(body_info.body_text[:300] if body_info else title),
                    canonical_fields={
                        "livepocket_url": app_url,
                        "body_score": body_info.score if body_info else 0,
                    },
                    extracted_payload={
                        "title": title,
                        "url": link,
                        "body_fetched": body_info is not None,
                        "body_score": body_info.score if body_info else 0,
                        "livepocket_url": app_url,
                    },
                )
            )
        return out
