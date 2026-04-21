"""ヤマダデンキ ポケモンカード抽選販売告知ページ adapter。

TOP ページ `https://www.yamada-denki.jp/` に掲載されるバナーから
`/information/YYMMDD_pokemon-card/` 形式の個別告知 URL を拾い、
各ページの本文から応募期間/当選発表/販売期間を抽出する。

evidence_type: store_notice (店舗公式の告知ページ)
sales_type: lottery
entry_method: app_only (ヤマダデジタル会員アプリ必須)
"""
from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..lib.body_extractor import extract_body_info
from ..lib.normalize import normalize_product_name
from ..lib.snapshot import content_hash
from ..lib.text_clean import clean_text
from .base import Candidate, SourceAdapter
from .http import fetch_text
from .registry import register_adapter

log = logging.getLogger(__name__)
BASE = "https://www.yamada-denki.jp"
TOP_URL = f"{BASE}/"
_INFO_URL_RE = re.compile(
    r"/information/(\d{6})_pokemon-card[^/\"]*/?", re.IGNORECASE
)
_TITLE_SUFFIX_RE = re.compile(r"\s*[｜|].*$")  # ｜ヤマダデンキ 以降を除去


def _extract_product_name_from_title(title: str) -> str:
    """「『ポケモンカードゲーム MEGA 拡張パック アビスアイ』の抽選販売お申し込み受付」等から商品名抽出。"""
    s = _TITLE_SUFFIX_RE.sub("", title).strip()
    # 「」 で囲まれた最初の固まりが商品名
    m = re.search(r"[「『]([^」』]+)[」』]", s)
    if m:
        return m.group(1).strip()
    # fallback: 「の抽選」より前
    if "の抽選" in s:
        return s.split("の抽選", 1)[0].strip()
    return s


@register_adapter("yamada_lottery")
class YamadaLotteryAdapter(SourceAdapter):
    """ヤマダデンキ 抽選販売告知ページ。

    TOP から個別告知ページの URL を拾い、per-run cap で本文を fetch する。
    """

    def __init__(
        self,
        *,
        top_html: str | None = None,
        body_fetcher=None,
        max_body_fetch: int = 5,
    ) -> None:
        self._top_html = top_html
        self._body_fetcher = body_fetcher
        self._max_body_fetch = max_body_fetch

    async def run(self) -> list[Candidate]:
        top_html = (
            self._top_html if self._top_html is not None else await fetch_text(TOP_URL)
        )
        # TOP HTML 中から /information/XXXXXX_pokemon-card/ を抽出
        seen: set[str] = set()
        paths: list[str] = []
        for m in _INFO_URL_RE.finditer(top_html):
            path = m.group(0)
            # 正規化: 末尾 / 付与
            if not path.endswith("/"):
                path = path + "/"
            if path in seen:
                continue
            seen.add(path)
            paths.append(path)
        if not paths:
            return []

        out: list[Candidate] = []
        fetched = 0
        for path in paths:
            if fetched >= self._max_body_fetch:
                break
            url = urljoin(BASE, path)
            try:
                body_html = (
                    await self._body_fetcher(url)
                    if self._body_fetcher
                    else await fetch_text(url)
                )
            except Exception as e:  # noqa: BLE001
                log.warning("yamada body fetch failed for %s: %s", url, e)
                continue
            fetched += 1

            soup = BeautifulSoup(body_html, "html.parser")
            title_tag = soup.find("title")
            raw_title = clean_text(title_tag.get_text(" ")) if title_tag else ""
            if not raw_title:
                continue

            product_name_raw = _extract_product_name_from_title(raw_title)
            product_name_normalized = normalize_product_name(product_name_raw)
            if not product_name_normalized or len(product_name_normalized) < 2:
                continue

            body_info = extract_body_info(body_html)
            # 応募期間が全く取れなかったページは抽選ページとして扱わない
            if not body_info.has_any_date:
                continue

            # sale_status_hint: 応募終了後かどうかの雑判定
            text = body_info.body_text
            is_ended = "受付は終了" in text or "応募は終了" in text
            sale_status_hint = "ended" if is_ended else "accepting"

            snapshot_src = body_html or (raw_title + "|" + url)

            out.append(
                Candidate(
                    product_name_raw=product_name_raw,
                    product_name_normalized=product_name_normalized,
                    retailer_name="yamada",
                    sales_type="lottery",
                    canonical_title=raw_title,
                    apply_start_at=body_info.apply_start_at,
                    apply_end_at=body_info.apply_end_at,
                    result_at=body_info.result_at,
                    purchase_start_at=body_info.purchase_start_at,
                    purchase_end_at=body_info.purchase_end_at,
                    purchase_limit_text=body_info.purchase_limit_text,
                    conditions_text=body_info.conditions_text,
                    source_name="yamada_lottery",
                    source_url=url,
                    source_title=raw_title,
                    raw_snapshot=content_hash(snapshot_src),
                    application_url=url,
                    entry_method="app_only",
                    sale_status_hint=sale_status_hint,
                    evidence_type="store_notice",
                    raw_text_excerpt=text[:300],
                    canonical_fields={
                        "is_ended": is_ended,
                        "body_score": body_info.score,
                    },
                    extracted_payload={
                        "url": url,
                        "title": raw_title,
                        "body_fetched": True,
                        "body_score": body_info.score,
                    },
                )
            )
        return out
