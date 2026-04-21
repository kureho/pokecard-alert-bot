"""sources 初期データ投入。__main__ の初回起動で冪等に呼び出される。"""

from __future__ import annotations

from .storage.repos import SourceRepo

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
]


async def seed_sources(repo: SourceRepo) -> None:
    for name, stype, url, trust in SEED_SOURCES:
        await repo.upsert(
            source_name=name,
            source_type=stype,
            base_url=url,
            trust_score=trust,
            is_active=True,
        )
