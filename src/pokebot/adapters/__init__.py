from .base import Candidate, SourceAdapter
from .registry import AdapterRegistry, register_adapter

# Side-effect imports: ensure each adapter registers itself in the AdapterRegistry.
# __main__ / service layer が名前解決できるよう、パッケージ import 時に全 adapter を読み込む。
from . import (  # noqa: F401
    biccamera_lottery,
    official_news,
    official_products,
    pokecen_online_guide,
    pokecen_online_lottery,
    pokecen_store_voice,
    yodobashi_lottery,
)

__all__ = ["Candidate", "SourceAdapter", "AdapterRegistry", "register_adapter"]
