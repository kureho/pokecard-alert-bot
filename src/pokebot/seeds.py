"""sources 初期データ投入。__main__ の初回起動で冪等に呼び出される。"""

from __future__ import annotations

from .storage.repos import SourceRepo

# 2026-04-22: 長期失敗で一時的に無効化する source。is_active=False でDBに保存され、
# silence_detector / adapter dispatch の両方から無視される。
# 復旧確認できたら set から外す。
# - yodobashi_lottery / amiami_lottery: 403 Forbidden (GHA US IP block)
# - amazon_search: 503 (Amazon Bot detection)
# - biccamera_lottery / pokecawatch_chusen: empty response
# - pokemoncenter_online_guide: adapter が Candidate を 1 件も返さない health 専用。
#   2026-04-22 から 403 が発生し silence 警告のみ無駄に発火するため無効化。
# - twitter_* (7 アカウント): 2026-04-23 現在、pacing 10s でも syndication.twitter.com が
#   全アカウントに対し 429 を返し続けている (IP ベースの rate limit と推定)。
#   公式 Twitter API (v2) へ移行するまで一時無効化。
DISABLED_SOURCES: frozenset[str] = frozenset(
    {
        # Akamai HTTP/2 fingerprint block で Supabase edge proxy (Deno fetch) でも突破不可。
        # Playwright 等 headless browser を使う別手段が必要。現状は保留。
        "yodobashi_lottery",
        "biccamera_lottery",
        # amazon の /s 検索 API は proxy 経由でも 503 (Bot 対策が商品検索に厳しい)。
        # トップ / 商品詳細なら取れるので、将来的に特定 ASIN を monitor する形に作り直す余地あり。
        "amazon_search",
        # Google News RSS の `rss/articles/<id>` は JS redirect 設計で、直接 GET すると
        # 400 で実 URL に辿り着けない (2026 現在の Google の Bot 対策)。source.href は
        # domain のみで個別記事 URL を含まないため本文 fetch 不可。Playwright 等で JS
        # 解決できる環境が用意できるまで保留。コードは将来再有効化を想定して残す。
        "google_news_rss",
        "pokecawatch_chusen",
        "pokemoncenter_online_guide",
        # 2026-04-23: まとめ記事系で一次情報ではない。audit 結果 events=8 で全 archived、
        # strong=0 / precision=0%。質優先方針に合わない。
        "nyuka_now_news",
        "twitter_pokecayoyaku",
        "twitter_pokecamatomeru",
        "twitter_pokecawatch",
        "twitter_beatdown",
        "twitter_ys_info",
        "twitter_usagiya_jounai",
        "twitter_t_sanoTCG",
    }
)

# (source_name, source_type, base_url, trust_score)
SEED_SOURCES: list[tuple[str, str, str, int]] = [
    (
        "pokemon_official_products",
        "official_product",
        "https://www.pokemon-card.com/products/",
        100,
    ),
    ("pokemon_official_news", "official_news", "https://www.pokemon-card.com/info/", 100),
    (
        "pokemoncenter_online_lottery",
        "official_lottery",
        "https://www.pokemoncenter-online.com/lottery/apply.html",
        100,
    ),
    (
        "pokemoncenter_online_guide",
        "official_lottery",
        "https://www.pokemoncenter-online.com/guide/guide-lottery.html",
        100,
    ),
    ("pokemoncenter_store_voice", "official_store_notice", "https://voice.pokemon.co.jp/stv/", 90),
    (
        "yodobashi_lottery",
        "retailer_lottery",
        "https://www.yodobashi.com/ec/special/other/54666/",
        95,
    ),
    (
        "biccamera_lottery",
        "retailer_lottery",
        "https://www.biccamera.com/bc/i/card/pokemoncard/index.jsp",
        95,
    ),
    # カードラボは主要 TCG 専門店で店舗ブログに抽選告知を直接掲載。trust=90 で confirmed 対象。
    ("c_labo_blog", "retailer_lottery", "https://www.c-labo.jp/blog/", 90),
    ("amiami_lottery", "retailer_lottery", "https://www.amiami.com/jp/event/lottery", 85),
    (
        "pokecawatch_chusen",
        "aggregator",
        "https://pokecawatch.com/category/%E6%8A%BD%E9%81%B8%E3%83%BB%E4%BA%88%E7%B4%84%E6%83%85%E5%A0%B1/feed",
        75,
    ),
    # Twitter syndication (unauth public profile)。手動キュレーション済の速報性高いソース。
    # 仕様変更で壊れやすいため trust=80 に抑える。
    (
        "twitter_pokecayoyaku",
        "social",
        "https://syndication.twitter.com/srv/timeline-profile/screen-name/pokecayoyaku",
        80,
    ),
    (
        "twitter_pokecamatomeru",
        "social",
        "https://syndication.twitter.com/srv/timeline-profile/screen-name/pokecamatomeru",
        80,
    ),
    (
        "twitter_pokecawatch",
        "social",
        "https://syndication.twitter.com/srv/timeline-profile/screen-name/pokecawatch",
        80,
    ),
    # 小規模店の独自速報 (trust=75)。フォロワー範囲は狭いが、店舗独自の
    # 抽選/招待告知を先出しすることが多い。クロスソース corroboration で
    # 他ソースと一致したら confirmed 昇格。
    (
        "twitter_beatdown",
        "social",
        "https://syndication.twitter.com/srv/timeline-profile/screen-name/BeatDownManager",
        75,
    ),
    (
        "twitter_ys_info",
        "social",
        "https://syndication.twitter.com/srv/timeline-profile/screen-name/YS_INFO",
        75,
    ),
    (
        "twitter_usagiya_jounai",
        "social",
        "https://syndication.twitter.com/srv/timeline-profile/screen-name/usagiya_jounai",
        75,
    ),
    (
        "twitter_t_sanoTCG",
        "social",
        "https://syndication.twitter.com/srv/timeline-profile/screen-name/T_sanoTCG",
        75,
    ),
    # nyuka-now: 販売予定・販路網羅のまとめ記事 RSS (aggregator)。
    # Amazon/楽天/ヨドバシ等の販売予定時刻を早期にまとめるため、apply_start_at 取得用に重視。
    (
        "nyuka_now_news",
        "aggregator",
        "https://nyuka-now.com/archives/category/news/feed",
        80,
    ),
    # Amazon search ASIN adapter: 予約/抽選/招待 kw を含む検索結果を候補化。
    # 通常在庫販売は除外しポケカ限定の予約/販売予告のみ拾う。
    (
        "amazon_search",
        "retailer_lottery",
        "https://www.amazon.co.jp/s?k=pokemon+card",
        85,
    ),
    # 楽天ブックス ポケモンカードゲーム抽選受付ページ (公式 entry page, EUC-JP)。
    # 商品別ではなく「楽天ブックス抽選枠」単位で期間情報を持つため trust=95。
    (
        "rakuten_books_entry",
        "retailer_lottery",
        "https://books.rakuten.co.jp/event/game/card/entry/",
        95,
    ),
    # ヤマダデンキ TOP → /information/YYMMDD_pokemon-card/ 告知。
    # 公式店舗告知で evidence_type=store_notice、trust=90 で confirmed 対象。
    (
        "yamada_lottery",
        "retailer_lottery",
        "https://www.yamada-denki.jp/",
        90,
    ),
    # ホビーステーション (hbst.net) RSS。ポケカ抽選告知を記事として密度高く投稿。
    # 記事本文に応募期間・当選発表・購入期間が定型記載、Livepocket URL あり。
    (
        "hbst_lottery",
        "retailer_lottery",
        "https://www.hbst.net/feed/",
        90,
    ),
    # Google News RSS アグリゲーター。domain whitelist で複数販売店 (トイザらス/HMV/
    # Joshin/GEO/イオン/SNKRDUNK 等) の抽選告知を 1 adapter で集約する。
    # 2次情報サイト / まとめ記事は adapter 内で skip。既存 adapter 管轄 domain も除外。
    (
        "google_news_rss",
        "aggregator",
        "https://news.google.com/rss/search",
        85,
    ),
    # rare-zaiko.blog.jp: 1 商品につき全国 600 店舗分の抽選情報を人間が集約した記事を
    # 掲載するブログ。RSS 経由で最新まとめ記事を検知 → table#myTable をパースして各行を
    # Candidate 化。都道府県 allowlist (オンライン/全国/東京 1都3県) で絞る。
    # 2 次集約情報なので trust_score=80、evidence_type=aggregator で confirmed_medium 止まり
    # → 他 adapter とクロスした時に confirmed_strong 昇格する設計。
    (
        "rare_zaiko_aggregator",
        "aggregator",
        "https://rare-zaiko.blog.jp/index.rdf",
        80,
    ),
]


async def seed_sources(repo: SourceRepo) -> None:
    for name, stype, url, trust in SEED_SOURCES:
        await repo.upsert(
            source_name=name,
            source_type=stype,
            base_url=url,
            trust_score=trust,
            is_active=name not in DISABLED_SOURCES,
        )
