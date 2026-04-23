"""rare-zaiko.blog.jp (★レアモノ在庫再販速報) の集約ブログを 1 adapter で取り込む。

このブログは「商品 1 つ」につき「全国 N 百店舗分の抽選販売情報」を 1 記事に構造化して
掲載している。カラム: 済 / 都道府県 / 店舗名 / 応募期間 / 抽選形式 / 当選発表日 / 備考。

我々が個別 retailer ごとに adapter を 30 本書いてイタチごっこするより、
ここを 1 本で取り込む方が圧倒的に効率的 (まとめの品質も高い)。

evidence_type: aggregator (集約ブログの 2 次情報。trust_score=80 想定で
confirmed_medium 相当 → 通知対象外。複数ソースで裏取れた場合に confidence 上昇)。

ユーザー方針 (Q1=a, 店舗受取は 1 都 3 県のみ) に合わせ、都道府県カラムで
「オンライン」「全国」「東京都」「神奈川県」「埼玉県」「千葉県」以外の店舗は除外。
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from time import mktime

import feedparser
from bs4 import BeautifulSoup

from ..lib.jp_datetime import parse_jp_datetime
from ..lib.normalize import normalize_product_name
from ..lib.snapshot import content_hash
from ..lib.text_clean import clean_text
from .base import Candidate, SourceAdapter
from .http import fetch_text
from .registry import register_adapter

log = logging.getLogger(__name__)

FEED_URL = "https://rare-zaiko.blog.jp/index.rdf"

# ポケカ関連 title のみ通す (スプラトゥーン他 TCG の記事も RSS に流れるため)。
# rare-zaiko の実際のポケカまとめ記事 title 例:
#   「拡張パック「アビスアイ」全国予約店舗まとめ」
#   「ポケモンカードゲーム MEGA ○○ 再販情報」
# → 「ポケモン」「ポケカ」「拡張パック」のいずれかを含むものを pokemon-likely 判定。
_POKEMON_KEYWORDS = (
    "ポケモンカード",
    "ポケモンカードゲーム",
    "ポケカ",
    "ポケモン",
    "拡張パック",  # rare-zaiko のポケカ系記事の主要ワード
)
_LOTTERY_KEYWORDS = ("予約", "抽選", "再販", "受付", "販売", "まとめ")

# ユーザーの居住圏 (Q1=a) 相当: 店舗受取が必要な抽選は東京 1 都 3 県のみ。
# "オンライン" "全国" は通販可能な抽選として通す。
_ALLOWED_REGIONS: frozenset[str] = frozenset(
    {"オンライン", "全国", "東京都", "神奈川県", "埼玉県", "千葉県"}
)

# 店舗名 prefix / 部分一致で retailer_name を正規化。
# 先頭から match するので長い prefix を先に置く。
_RETAILER_PATTERNS: list[tuple[str, str]] = [
    ("Amazon", "amazon"),
    ("楽天ブックス", "rakuten_books"),
    ("楽天", "rakuten"),
    ("あみあみ", "amiami"),
    ("セブンネット", "seven_net"),
    ("ホビーサーチ", "hobby_search"),
    ("ヨドバシ", "yodobashi"),
    ("ビックカメラ", "biccamera"),
    ("ビック", "biccamera"),
    ("ソフマップ", "sofmap"),
    ("コジマ", "kojima"),
    ("Joshin", "joshin"),
    ("ジョーシン", "joshin"),
    ("エディオン", "edion"),
    ("ケーズデンキ", "ksdenki"),
    ("ヤマダ", "yamada"),
    ("TSUTAYA", "tsutaya"),
    ("ツタヤ", "tsutaya"),
    ("GEO", "geo"),
    ("ゲオ", "geo"),
    ("トイザらス", "toysrus"),
    ("ベビザらス", "babyrus"),
    ("HMV", "hmv"),
    ("キッズリパブリック", "kids_republic"),
    ("イオン", "aeon"),
    ("ホビーステーション", "hbst"),
    ("カードラボ", "cardlabo"),
    ("ポケモンセンター", "pokemoncenter"),
    ("ポケセン", "pokemoncenter"),
    ("駿河屋", "suruga_ya"),
    ("ふるいち", "furu1"),
    ("スニーカーダンク", "snkrdunk"),
    ("お宝創庫", "otakarasouko"),
    ("ヤマシロヤ", "yamashiroya"),
    ("ドラゴンスター", "dragon_star"),
    ("晴れる屋", "hareruya"),
    ("HOBBY ZONE", "hobby_zone"),
    ("ホビーゾーン", "hobby_zone"),
    ("ファミマ", "famima"),
    ("フタバ図書", "futaba"),
    ("ノジマ", "nojima"),
    ("Joshin web", "joshin"),
    ("三洋堂", "sanyodo"),
    ("平和堂", "heiwado"),
    ("LivePocket", "livepocket"),
    ("パスマーケット", "passmarket"),
    ("イトーヨーカドー", "ito_yokado"),
]

# 「抽選形式」カラムの文字列 → sales_type。
_SALES_TYPE_PATTERNS: list[tuple[str, str]] = [
    ("予約抽選", "preorder_lottery"),
    ("抽選予約", "preorder_lottery"),
    ("WEB抽選", "lottery"),
    ("店頭抽選", "lottery"),
    ("抽選販売", "lottery"),
    ("オンライン抽選", "lottery"),
    ("招待", "invitation"),
    ("整理券", "numbered_ticket"),
    ("番号札", "numbered_ticket"),
    ("先着", "first_come"),
]

# 記事タイトルから商品名を抽出: 「...」で囲まれた部分を採用。
_QUOTED_PRODUCT_RE = re.compile(r"[「『]([^」』]+)[」』]")


def _extract_product_name_from_title(title: str) -> str | None:
    """記事タイトル「拡張パック「アビスアイ」全国予約店舗まとめ」→ 「アビスアイ」。"""
    m = _QUOTED_PRODUCT_RE.search(title)
    if m:
        return m.group(1).strip()
    # フォールバック: 「予約」「抽選」「まとめ」等の前まで
    return clean_text(title).split("全国")[0].strip() or None


def _normalize_retailer(store_name: str) -> str:
    """店舗名から retailer_name を決める。未登録は "unknown" を返す。"""
    s = store_name or ""
    for pat, ret in _RETAILER_PATTERNS:
        if pat.lower() in s.lower():
            return ret
    return "unknown"


def _infer_sales_type(lottery_form: str) -> str:
    """抽選形式カラムから sales_type を決定。該当なしは unknown。"""
    s = lottery_form or ""
    for pat, st in _SALES_TYPE_PATTERNS:
        if pat in s:
            return st
    return "unknown"


def _parse_apply_end(apply_period_str: str, *, now: datetime) -> datetime | None:
    """「4月22日(水)13:59まで」等から apply_end_at を取り出す。

    年情報は含まれないため、now 基準で「過去になる場合は次の年」と判断する。
    """
    s = (apply_period_str or "").strip()
    if not s:
        return None
    # 末尾 "まで" を除去
    s_clean = s.rstrip("まで").rstrip("迄").strip()
    parsed = parse_jp_datetime(s_clean)
    if parsed is None:
        return None
    # 年補正: 現在より 30 日以上過去なら翌年扱い
    if (now - parsed).days > 30:
        parsed = parsed.replace(year=parsed.year + 1)
    return parsed


def _is_pokemon_and_lottery_article(title: str) -> bool:
    if not any(k in title for k in _POKEMON_KEYWORDS):
        return False
    if not any(k in title for k in _LOTTERY_KEYWORDS):
        return False
    return True


@register_adapter("rare_zaiko_aggregator")
class RareZaikoAggregatorAdapter(SourceAdapter):
    """rare-zaiko.blog.jp 集約ブログの記事 table を candidate 化。

    - RSS (index.rdf) で最新記事を検知
    - ポケカ + 予約/抽選 title の記事のみ fetch
    - table#myTable の各行を Candidate に変換
    - 都道府県が "オンライン/全国/東京近郊" 以外は skip (ユーザー方針)
    - 抽選形式 unknown の行は skip (質優先、ノイズ防止)
    - source_published_at は RSS の pubDate を使う
    """

    source_name = "rare_zaiko_aggregator"

    def __init__(
        self,
        *,
        xml: str | None = None,
        article_fetcher=None,
        max_articles: int = 5,
        max_rows_per_article: int = 500,
    ) -> None:
        """xml / article_fetcher はテスト注入用。max_articles でレート抑制。"""
        self._xml = xml
        self._article_fetcher = article_fetcher
        self._max_articles = max_articles
        self._max_rows = max_rows_per_article

    async def _fetch_article(self, url: str) -> str:
        if self._article_fetcher:
            return await self._article_fetcher(url)
        return await fetch_text(url)

    def _parse_article_rows(
        self, html: str
    ) -> list[dict]:
        """記事 HTML から table#myTable の各行を dict list で返す。"""
        soup = BeautifulSoup(html, "html.parser")
        table = soup.select_one("table#myTable")
        if not table:
            return []
        rows: list[dict] = []
        for tr in table.select("tbody tr")[: self._max_rows]:
            cells = [c.get_text(" ", strip=True) for c in tr.select("td")]
            if len(cells) < 5:
                continue
            # [済, 都道府県, 店舗名, 応募期間, 抽選形式, 当選発表日, 備考]
            rows.append(
                {
                    "done": cells[0] if len(cells) > 0 else "",
                    "region": cells[1] if len(cells) > 1 else "",
                    "store": cells[2] if len(cells) > 2 else "",
                    "apply_period": cells[3] if len(cells) > 3 else "",
                    "lottery_form": cells[4] if len(cells) > 4 else "",
                    "result_at": cells[5] if len(cells) > 5 else "",
                    "note": cells[6] if len(cells) > 6 else "",
                }
            )
        return rows

    async def run(self) -> list[Candidate]:
        xml = self._xml if self._xml is not None else await fetch_text(FEED_URL)
        parsed = feedparser.parse(xml)
        out: list[Candidate] = []
        article_count = 0
        now = datetime.now()

        for entry in parsed.entries:
            if article_count >= self._max_articles:
                break
            title = (entry.get("title") or "").strip()
            link = (entry.get("link") or "").strip()
            if not title or not link:
                continue
            if not _is_pokemon_and_lottery_article(title):
                continue

            # 年補正用の published
            published = None
            if getattr(entry, "published_parsed", None):
                try:
                    published = datetime.fromtimestamp(mktime(entry.published_parsed))
                except Exception:  # noqa: BLE001
                    published = None

            product_name_raw = _extract_product_name_from_title(title) or title
            product_name_normalized = normalize_product_name(product_name_raw)

            try:
                article_html = await self._fetch_article(link)
            except Exception as e:  # noqa: BLE001
                log.warning("rare_zaiko article fetch failed for %s: %s", link, e)
                continue

            article_count += 1
            rows = self._parse_article_rows(article_html)

            for row in rows:
                region = (row["region"] or "").strip()
                if region not in _ALLOWED_REGIONS:
                    continue

                lottery_form = row["lottery_form"] or ""
                sales_type = _infer_sales_type(lottery_form)
                if sales_type == "unknown":
                    # 質優先: 抽選形式判別不能な行は candidate 発行しない
                    continue

                store = (row["store"] or "").strip()
                if not store:
                    continue

                retailer = _normalize_retailer(store)

                apply_end = _parse_apply_end(row["apply_period"], now=now)
                result_at = _parse_apply_end(row["result_at"], now=now)
                note = clean_text(row["note"])[:500] if row["note"] else None

                snapshot_src = f"{link}|{store}|{row['apply_period']}|{lottery_form}"

                out.append(Candidate(
                    product_name_raw=product_name_raw,
                    product_name_normalized=product_name_normalized,
                    retailer_name=retailer,
                    store_name=store,
                    sales_type=sales_type,
                    canonical_title=f"{product_name_raw} / {store}",
                    apply_start_at=None,  # まとめには開始時刻が無いことが多い
                    apply_end_at=apply_end,
                    result_at=result_at,
                    purchase_start_at=None,
                    purchase_end_at=None,
                    purchase_limit_text=None,
                    conditions_text=note,
                    source_name="rare_zaiko_aggregator",
                    source_url=link,
                    source_title=title,
                    source_published_at=published,
                    raw_snapshot=content_hash(snapshot_src),
                    extracted_payload={
                        "title": title,
                        "url": link,
                        "region": region,
                        "store": store,
                        "apply_period": row["apply_period"],
                        "lottery_form": lottery_form,
                        "result_at_text": row["result_at"],
                        "body_fetched": True,
                    },
                    evidence_type="aggregator",
                    application_url=link,
                ))
        return out
