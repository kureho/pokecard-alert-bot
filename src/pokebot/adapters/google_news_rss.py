"""Google News RSS で複数販売店の抽選告知を 1 adapter で集約。

Google News の検索 RSS (`news.google.com/rss/search?q=...`) に「ポケモンカード 抽選」で
クエリを投げ、返ってくる記事タイトル + link を全販売店横断の candidate source として使う。

方針 (質 > 量):
- domain whitelist で信頼できる一次情報源 (販売店公式) のみ通す
- 既存 adapter でカバー済みの domain は除外 (重複回避)
- まとめ記事 / アフィ記事 / 2 次情報サイトは allowlist 外で自動 skip
- title に「まとめ」「一覧」を含む記事は、allowlist 内でも skip
- Google News の redirect link は HEAD で実 URL に解決する (domain 判定に必須)

evidence_type: store_notice (販売店公式告知)
"""
from __future__ import annotations

import logging
from datetime import datetime
from time import mktime
from urllib.parse import urlparse

import feedparser
import httpx

from ..lib.body_extractor import extract_body_info
from ..lib.normalize import normalize_product_name
from ..lib.snapshot import content_hash
from ..lib.text_clean import clean_text
from ..lib.title_classifier import TitleCategory, classify_title
from .base import Candidate, SourceAdapter
from .http import fetch_text
from .registry import register_adapter

log = logging.getLogger(__name__)

# Google News 検索 RSS。クエリは URL-encoded で
# "ポケモンカード 抽選" を渡す。他条件は hl/gl/ceid で日本向けに固定。
FEED_URL = (
    "https://news.google.com/rss/search?"
    "q=%E3%83%9D%E3%82%B1%E3%83%A2%E3%83%B3%E3%82%AB%E3%83%BC%E3%83%89+%E6%8A%BD%E9%81%B8"
    "&hl=ja&gl=JP&ceid=JP:ja"
)

# 通すべき一次情報源 (販売店公式)。domain -> retailer_name のマップ。
# 質優先方針: whitelist 方式 (未登録 domain はノイズとみなし skip)
ALLOWED_DOMAINS: dict[str, str] = {
    "www.toysrus.co.jp": "toysrus",
    "www.hmv.co.jp": "hmv",
    "shop.joshin.co.jp": "joshin",
    "joshinweb.jp": "joshin",
    "ec.geo-online.co.jp": "geo",
    "7net.omni7.jp": "seven_net",
    "www.aeonretail.com": "aeon",
    "iaeon.jp": "aeon",
    "www.kidsrepublic.jp": "kids_republic",
    "snkrdunk.com": "snkrdunk",
    "hobby-zone.net": "hobby_zone",
    "dorasuta.membercard.jp": "dragon_star",
    "www.hareruya2.com": "hareruya2",
    "furu1.net": "furu1",
    "otakarasouko.com": "otakarasouko",
    "www.e-yamashiroya.com": "yamashiroya",
    "www.suruga-ya.jp": "suruga_ya",
    # 公式系の補完 (既存 adapter でも拾うが、漏れ対策として)
    "www.pokemon-card.com": "pokemon_official",
}

# 既存 adapter で同じ告知を拾っているため、このドメインは Google News 経由では取らない。
# (重複 insert は content_dedupe_key で防げるが、無駄な body fetch を避ける)
EXCLUDED_DOMAINS: frozenset[str] = frozenset(
    {
        "voice.pokemon.co.jp",            # pokemoncenter_store_voice
        "www.hbst.net",                   # hbst_lottery
        "www.c-labo.jp",                  # c_labo_blog
        "www.pokemoncenter-online.com",   # pokemoncenter_online_lottery
        "books.rakuten.co.jp",            # rakuten_books_entry
        "item.rakuten.co.jp",             # 楽天系商品ページ
        "www.yamada-denki.jp",            # yamada_lottery
        "www.amiami.com",                 # amiami_lottery
        "www.amiami.jp",
    }
)

# 「まとめ」「一覧」「ランキング」等の 2 次情報・まとめ記事を弾くキーワード。
# allowlist 内 domain でも title に含まれていれば skip。
_SUMMARY_KEYWORDS = ("まとめ", "一覧", "ランキング", "情報", "解説", "比較")

_POKEMON_KEYWORDS = ("ポケモンカード", "ポケモンカードゲーム", "ポケカ")
_LOTTERY_KEYWORDS = ("抽選", "予約", "応募", "受付")


async def _resolve_redirect(url: str, timeout: float = 10.0) -> str:
    """Google News の redirect URL を実 URL に解決。

    news.google.com/rss/articles/<id>?oc=5 → 実ニュース記事 URL への redirect を follow。
    失敗時は元 URL をそのまま返す (後段の domain 判定で弾かれる)。
    """
    try:
        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=True, max_redirects=5
        ) as client:
            resp = await client.head(url)
            final = str(resp.url)
            if final and final != url:
                return final
            # HEAD で Location が来ない場合は GET で redirect chain を追う
            resp = await client.get(url)
            return str(resp.url)
    except Exception as e:  # noqa: BLE001
        log.warning("google_news_rss: redirect resolve failed for %s: %s", url[:80], e)
        return url


def _title_has_pokemon(title: str) -> bool:
    return any(k in title for k in _POKEMON_KEYWORDS)


def _title_has_lottery_keyword(title: str) -> bool:
    return any(k in title for k in _LOTTERY_KEYWORDS)


def _title_is_summary(title: str) -> bool:
    return any(k in title for k in _SUMMARY_KEYWORDS)


@register_adapter("google_news_rss")
class GoogleNewsRssAdapter(SourceAdapter):
    """Google News RSS で複数販売店の抽選告知を横断取得。

    - feed の最新 40 件からポケカ + 抽選系を抽出
    - Google News redirect URL を解決して実ドメイン特定
    - ALLOWED_DOMAINS のみ candidate 化 (whitelist 方式)
    - 既存 adapter 管轄 (EXCLUDED_DOMAINS) は除外
    - まとめ記事 (タイトルに「まとめ」「一覧」等) は除外
    - 本文 fetch で sales_type / 応募期間を body_extractor で抽出
    """

    source_name = "google_news_rss"

    def __init__(
        self,
        *,
        xml: str | None = None,
        redirect_resolver=None,
        body_fetcher=None,
        max_body_fetch: int = 10,
    ) -> None:
        """xml / redirect_resolver / body_fetcher はテスト注入用。"""
        self._xml = xml
        self._resolve = redirect_resolver or _resolve_redirect
        self._body_fetcher = body_fetcher
        self._max_body_fetch = max_body_fetch

    async def run(self) -> list[Candidate]:
        xml = self._xml if self._xml is not None else await fetch_text(FEED_URL)
        parsed = feedparser.parse(xml)
        out: list[Candidate] = []
        fetched = 0
        for e in parsed.entries[:40]:
            title = (e.get("title") or "").strip()
            link = (e.get("link") or "").strip()
            if not title or not link:
                continue

            # (1) title でポケカ + 抽選系キーワードで絞る
            if not _title_has_pokemon(title):
                continue
            if not _title_has_lottery_keyword(title):
                continue

            # (2) まとめ / 一覧系は skip
            if _title_is_summary(title):
                continue

            # (3) classify_title で過去イベ / 結果発表のみ弾く。
            # IRRELEVANT は通す: 既に title の lottery キーワード絞り込みでノイズを減らしており、
            # classify_title の辞書に載っていない「抽選販売のお知らせ」等の言い回しも救える。
            analysis = classify_title(title)
            if analysis.category in (
                TitleCategory.LOTTERY_CLOSED,
                TitleCategory.LOTTERY_RESULT,
            ):
                continue

            # (4) Google News redirect を実 URL に解決
            final_url = await self._resolve(link)
            try:
                parsed_url = urlparse(final_url)
            except Exception:  # noqa: BLE001
                continue
            host = parsed_url.hostname or ""

            # (5) excluded domain (既存 adapter 管轄) は skip
            if host in EXCLUDED_DOMAINS:
                continue

            # (6) whitelist 判定
            retailer = ALLOWED_DOMAINS.get(host)
            if retailer is None:
                continue

            published = None
            if getattr(e, "published_parsed", None):
                try:
                    published = datetime.fromtimestamp(mktime(e.published_parsed))
                except Exception:  # noqa: BLE001
                    published = None

            # (7) 本文 fetch で sales_type + 応募期間を確定
            body_info = None
            body_html = None
            if fetched < self._max_body_fetch:
                try:
                    body_html = (
                        await self._body_fetcher(final_url) if self._body_fetcher
                        else await fetch_text(final_url)
                    )
                    body_info = extract_body_info(body_html)
                    fetched += 1
                except Exception as ex:  # noqa: BLE001
                    log.warning(
                        "google_news_rss body fetch failed for %s: %s", final_url[:80], ex
                    )

            # (8) sales_type 確定: title → body の順
            sales_type = analysis.inferred_sales_type
            if sales_type == "unknown" and body_info:
                sales_type = body_info.inferred_sales_type
            # 判別不能なら candidate 発行しない
            if sales_type == "unknown":
                continue

            # 商品名: body の h1/title を優先
            if body_info and body_info.product_name:
                product_name_raw = clean_text(body_info.product_name)
                product_name_normalized = normalize_product_name(body_info.product_name)
            else:
                product_name_raw = clean_text(title)
                product_name_normalized = normalize_product_name(title)

            snapshot_src = body_html if body_html else (title + "|" + final_url)

            out.append(Candidate(
                product_name_raw=product_name_raw,
                product_name_normalized=product_name_normalized,
                retailer_name=retailer,
                sales_type=sales_type,
                canonical_title=title,
                apply_start_at=body_info.apply_start_at if body_info else None,
                apply_end_at=body_info.apply_end_at if body_info else None,
                result_at=body_info.result_at if body_info else None,
                purchase_start_at=body_info.purchase_start_at if body_info else None,
                purchase_end_at=body_info.purchase_end_at if body_info else None,
                purchase_limit_text=body_info.purchase_limit_text if body_info else None,
                conditions_text=body_info.conditions_text if body_info else None,
                source_name="google_news_rss",
                source_url=final_url,
                source_title=title,
                source_published_at=published,
                raw_snapshot=content_hash(snapshot_src),
                extracted_payload={
                    "title": title,
                    "url": final_url,
                    "host": host,
                    "google_news_link": link,
                    "title_category": str(analysis.category),
                    "body_fetched": body_info is not None,
                    "body_score": body_info.score if body_info else 0,
                },
                evidence_type="store_notice",
                application_url=final_url,
            ))
        return out
