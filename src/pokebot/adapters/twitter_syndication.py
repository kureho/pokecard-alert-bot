"""Twitter syndication API 経由で公開 profile timeline を取得する adapter。

- 認証不要 (`syndication.twitter.com/srv/timeline-profile/screen-name/{user}`)
- HTML の `<script id="__NEXT_DATA__">` から JSON 抽出
- tweet.full_text からポケカ関連を filter
- sales_type: 招待/抽選/先着 を text から推定
- retailer_name: Amazon/ポケセン/ヨドバシ等を text に含まれるキーワードから推定

Twitter 側の仕様変更で壊れる可能性あり。壊れた場合は source_health に記録されて
SilenceDetector が警告する。
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from email.utils import parsedate_to_datetime

from ..lib.normalize import normalize_product_name
from ..lib.snapshot import content_hash
from ..lib.text_clean import clean_text
from ..lib.title_classifier import TitleCategory, classify_title
from .base import Candidate, SourceAdapter
from .http import fetch_text
from .registry import register_adapter

log = logging.getLogger(__name__)

_NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_POKEMON_KEYWORDS = ("ポケモンカード", "ポケモンカードゲーム", "ポケカ")
_MAX_ENTRIES_PER_ACCOUNT = 30


def _parse_tweets(html: str) -> list[dict]:
    """syndication profile HTML から tweet dict のリストを抽出。"""
    m = _NEXT_DATA_RE.search(html)
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return []
    entries = (
        data.get("props", {}).get("pageProps", {}).get("timeline", {}).get("entries", [])
    )
    tweets: list[dict] = []
    for e in entries:
        t = e.get("content", {}).get("tweet")
        if t:
            tweets.append(t)
    return tweets


def _parse_twitter_date(s: str) -> datetime | None:
    """Twitter API 日付形式 "Mon Apr 20 05:04:14 +0000 2026" を naive UTC datetime に。"""
    if not s:
        return None
    try:
        dt = parsedate_to_datetime(s)
        # naive に統一 (他フィールドと揃える)
        return dt.replace(tzinfo=None) if dt.tzinfo else dt
    except (TypeError, ValueError):
        return None


_RETAILER_KEYWORDS = [
    ("ポケモンセンター", "pokemoncenter"),
    ("ポケセン", "pokemoncenter"),
    ("Amazon", "amazon"),
    ("アマゾン", "amazon"),
    ("ヨドバシ", "yodobashi"),
    ("ビックカメラ", "biccamera"),
    ("あみあみ", "amiami"),
    ("Joshin", "joshin"),
    ("ジョーシン", "joshin"),
    ("ヤマダデンキ", "yamada"),
    ("ヤマダ電機", "yamada"),
    ("カードラボ", "cardlabo"),
    ("駿河屋", "surugaya"),
    ("セブンネット", "seven_net"),
    ("TSUTAYA", "tsutaya"),
    ("楽天", "rakuten"),
    ("ノジマ", "nojima"),
    ("エディオン", "edion"),
    ("イオン", "aeon"),
]


def _detect_retailer(text: str) -> str:
    for kw, canon in _RETAILER_KEYWORDS:
        if kw in text:
            return canon
    return "unknown"


_SALES_TYPE_KEYWORDS = [
    ("招待制", "invitation"),
    ("招待リクエスト", "invitation"),
    ("招待", "invitation"),
    ("抽選販売", "lottery"),
    ("抽選予約", "preorder_lottery"),
    ("抽選", "lottery"),
    ("先着", "first_come"),
    ("整理券", "numbered_ticket"),
]


def _detect_sales_type(text: str) -> str:
    for kw, stype in _SALES_TYPE_KEYWORDS:
        if kw in text:
            return stype
    return "unknown"


# 「」『』内の商品名を抽出 (複数あれば最初のもの)
_QUOTED_RE = re.compile(r"[「『]([^」』]+)[」』]")


def _extract_product_candidate(text: str) -> str:
    m = _QUOTED_RE.search(text)
    if m:
        candidate = m.group(1).strip()
        if candidate and len(candidate) <= 80:
            return candidate
    # fallback: 先頭行 or URL まで
    first_line = text.split("\n", 1)[0]
    first_line = first_line.split("https://", 1)[0]
    return first_line[:80].strip()


class _TwitterSyndicationBase(SourceAdapter):
    """共通ロジック。サブクラスで ``account`` を指定する。"""

    account: str = ""

    def __init__(self, *, html: str | None = None) -> None:
        self._html = html

    async def run(self) -> list[Candidate]:
        url = (
            f"https://syndication.twitter.com/srv/timeline-profile/screen-name/{self.account}"
        )
        html = self._html if self._html is not None else await fetch_text(url)
        tweets = _parse_tweets(html)
        out: list[Candidate] = []
        for t in tweets[:_MAX_ENTRIES_PER_ACCOUNT]:
            text = t.get("full_text") or t.get("text") or ""
            if not text:
                continue
            if not any(k in text for k in _POKEMON_KEYWORDS):
                continue

            analysis = classify_title(text)
            # Twitter tweet は classifier の厳密 keyword 辞書から外れることが多い。
            # 過去イベント (当選者発表/受付終了) だけ確実に除外し、残りは
            # tweet 独自の _detect_sales_type で判定する。
            if analysis.category in (
                TitleCategory.LOTTERY_CLOSED,
                TitleCategory.LOTTERY_RESULT,
            ):
                continue

            sales_type = analysis.inferred_sales_type
            detected = _detect_sales_type(text)
            if sales_type == "unknown" and detected != "unknown":
                sales_type = detected
            # IRRELEVANT でも sales_type が detected なら採用 (招待/先着 tweet を拾うため)
            if analysis.category == TitleCategory.IRRELEVANT and sales_type == "unknown":
                continue

            tweet_id = str(t.get("id_str") or t.get("id") or "")
            permalink = t.get("permalink") or ""
            url_full = f"https://twitter.com{permalink}" if permalink else ""
            created_at = _parse_twitter_date(t.get("created_at", ""))

            product_core = _extract_product_candidate(text)
            product_name_raw = clean_text(product_core)
            product_name_normalized = normalize_product_name(product_core)
            if not product_name_normalized or len(product_name_normalized) < 2:
                continue

            retailer = _detect_retailer(text)
            title_for_event = text.split("\n", 1)[0][:200]

            out.append(
                Candidate(
                    product_name_raw=product_name_raw,
                    product_name_normalized=product_name_normalized,
                    retailer_name=retailer,
                    store_name=f"@{self.account}",
                    sales_type=sales_type,
                    canonical_title=title_for_event,
                    source_name=self.source_name,
                    source_url=url_full,
                    source_title=title_for_event,
                    source_published_at=created_at,
                    raw_snapshot=content_hash(tweet_id or text[:200]),
                    extracted_payload={
                        "tweet_id": tweet_id,
                        "account": self.account,
                        "text_preview": text[:500],
                        "detected_retailer": retailer,
                    },
                    evidence_type="social_post",
                    raw_text_excerpt=text[:500],
                    retailer_event_id=tweet_id or None,
                )
            )
        return out


@register_adapter("twitter_pokecayoyaku")
class TwitterPokecayoyakuAdapter(_TwitterSyndicationBase):
    account = "pokecayoyaku"


@register_adapter("twitter_pokecamatomeru")
class TwitterPokecamatomeruAdapter(_TwitterSyndicationBase):
    account = "pokecamatomeru"


@register_adapter("twitter_pokecawatch")
class TwitterPokecawatchAdapter(_TwitterSyndicationBase):
    account = "pokecawatch"


@register_adapter("twitter_beatdown")
class TwitterBeatdownAdapter(_TwitterSyndicationBase):
    account = "BeatDownManager"


@register_adapter("twitter_ys_info")
class TwitterYsInfoAdapter(_TwitterSyndicationBase):
    account = "YS_INFO"


@register_adapter("twitter_usagiya_jounai")
class TwitterUsagiyaJounaiAdapter(_TwitterSyndicationBase):
    account = "usagiya_jounai"


@register_adapter("twitter_t_sanoTCG")
class TwitterTSanoTCGAdapter(_TwitterSyndicationBase):
    account = "T_sanoTCG"
