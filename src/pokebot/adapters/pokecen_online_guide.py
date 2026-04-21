from __future__ import annotations

from bs4 import BeautifulSoup

from ..lib.snapshot import content_hash
from .base import Candidate, SourceAdapter
from .http import fetch_text
from .registry import register_adapter

BASE = "https://www.pokemoncenter-online.com"
URL = f"{BASE}/guide/guide-lottery.html"


@register_adapter("pokemoncenter_online_guide")
class PokecenOnlineGuideAdapter(SourceAdapter):
    """抽選ガイド。通常は静的だが新規告知が追加される可能性を追跡する。"""

    def __init__(self, *, html: str | None = None) -> None:
        self._html = html

    async def run(self) -> list[Candidate]:
        html = self._html if self._html is not None else await fetch_text(URL)
        # 静的ページ内容のハッシュだけ返す。source_health 側の更新検知に使う。
        # Phase 1 では Candidate を返さず、fetch が成功したら health が記録される想定。
        _ = BeautifulSoup(html, "html.parser")
        _ = content_hash(html)
        return []
