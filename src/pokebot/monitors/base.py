from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable

from .types import RawItem


class Monitor(ABC):
    id: str
    interval_sec: int

    @abstractmethod
    async def fetch(self) -> Iterable[RawItem]:
        """外部ソースから最新データを取得し、RawItem 列を返す。失敗時は例外を投げる。"""
