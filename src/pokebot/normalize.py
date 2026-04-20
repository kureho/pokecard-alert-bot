from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import date

CATEGORIES = ["強化拡張パック", "ハイクラスパック", "拡張パック", "プロモパック"]
BOX_WORDS = ["BOX", "Box", "ボックス"]
STATUS_PREFIXES = ["抽選販売", "抽選", "予約", "再販", "入荷"]

_BRACKETS = str.maketrans({c: "" for c in "【】「」『』[]()（）"})


def _nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", s)


@dataclass
class NormalizedProduct:
    product_name: str
    category: str | None
    is_box: bool
    raw: str

    def key(self, *, release_date: date | None = None, url: str | None = None) -> str:
        cat = self.category or "?"
        box = "BOX" if self.is_box else "PACK"
        if release_date is not None:
            date_part = release_date.isoformat()
        elif url:
            h = hashlib.sha256(url.encode("utf-8")).hexdigest()[:10]
            date_part = f"uid={h}"
        else:
            h = hashlib.sha256(self.raw.encode("utf-8")).hexdigest()[:10]
            date_part = f"uid={h}"
        return f"{cat}|{self.product_name}|{date_part}|{box}"


def normalize_title(raw: str) -> NormalizedProduct:
    s = _nfkc(raw).translate(_BRACKETS)
    for p in STATUS_PREFIXES:
        s = s.replace(p, " ")
    s = re.sub(r"^\s*ポケモンカード(ゲーム)?\s*", "", s)
    s = s.strip()
    category: str | None = None
    for c in CATEGORIES:
        if c in s:
            category = c
            s = s.replace(c, " ").strip()
            break
    is_box = any(b in s for b in BOX_WORDS) or "30パック" in s or "カートン" in s
    for b in BOX_WORDS + ["30パック入", "30パック", "カートン"]:
        s = s.replace(b, " ")
    name = re.sub(r"\s+", " ", s).strip()
    return NormalizedProduct(product_name=name, category=category, is_box=is_box, raw=raw)
