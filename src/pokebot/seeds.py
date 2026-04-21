"""sources 初期データ投入。__main__ の初回起動で冪等に呼び出される。"""
from __future__ import annotations

from .storage.repos import SourceRepo

# (source_name, source_type, base_url, trust_score)
SEED_SOURCES: list[tuple[str, str, str, int]] = [
    ("pokemon_official_products", "official_product", "https://www.pokemon-card.com/products/", 100),
    ("pokemon_official_news", "official_news", "https://www.pokemon-card.com/info/", 100),
    ("pokemoncenter_online_lottery", "official_lottery", "https://www.pokemoncenter-online.com/lottery/apply.html", 100),
    ("pokemoncenter_online_guide", "official_lottery", "https://www.pokemoncenter-online.com/guide/guide-lottery.html", 100),
    ("pokemoncenter_store_voice", "official_store_notice", "https://voice.pokemon.co.jp/stv/", 90),
    ("yodobashi_lottery", "retailer_lottery", "https://www.yodobashi.com/ec/special/other/54666/", 95),
    ("biccamera_lottery", "retailer_lottery", "https://www.biccamera.com/bc/i/card/pokemoncard/index.jsp", 95),
]


async def seed_sources(repo: SourceRepo) -> None:
    for name, stype, url, trust in SEED_SOURCES:
        await repo.upsert(
            source_name=name, source_type=stype, base_url=url,
            trust_score=trust, is_active=True,
        )
