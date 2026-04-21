from .base import Candidate, SourceAdapter
from .registry import AdapterRegistry, register_adapter

# Side-effect imports: ensure each adapter registers itself in the AdapterRegistry.
# __main__ / service layer が名前解決できるよう、パッケージ import 時に全 adapter を読み込む。
from . import (  # noqa: F401
    amazon_search,
    amiami_lottery,
    biccamera_lottery,
    c_labo_blog,
    nyuka_now_news,
    official_news,
    official_products,
    pokecawatch_chusen,
    pokecen_online_guide,
    pokecen_online_lottery,
    pokecen_store_voice,
    twitter_syndication,
    yodobashi_lottery,
)

__all__ = ["Candidate", "SourceAdapter", "AdapterRegistry", "register_adapter"]
