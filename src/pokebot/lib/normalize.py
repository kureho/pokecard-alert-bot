from __future__ import annotations

import re
import unicodedata

_BRAND_PREFIXES = [
    "ポケモンカードゲーム スカーレット＆バイオレット",
    "ポケモンカードゲーム",
    "ポケモンカード",
]
_TYPE_PREFIXES = [
    "強化拡張パック",
    "ハイクラスパック",
    "拡張パック",
    "プロモパック",
    "スターターセット",
    "スタートデッキ",
    "スペシャルBOX",
    "スペシャルデッキセット",
]
_FORM_SUFFIXES = [
    "30パック入り", "30パック入", "30パック",
    "カートン",
    "1BOX", "BOX", "Box", "ボックス",
]
_BRACKETS = str.maketrans({c: "" for c in "【】「」『』[]()（）"})


def _nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", s)


def normalize_product_name(raw: str) -> str:
    """Strip brand/type/form decorators and return the core product identifier.

    Examples:
      アビスアイ / 拡張パック アビスアイ / ポケモンカードゲーム 拡張パック アビスアイ BOX
      → アビスアイ
    """
    s = _nfkc(raw).translate(_BRACKETS)
    s = re.sub(r"\s+", " ", s).strip()
    for p in _BRAND_PREFIXES:
        s = re.sub(rf"^{re.escape(p)}\s*", "", s)
    for p in _TYPE_PREFIXES:
        s = re.sub(rf"^{re.escape(p)}\s*", "", s)
        s = re.sub(rf"\s*{re.escape(p)}\s*", " ", s)
    for b in _FORM_SUFFIXES:
        s = re.sub(rf"\s*{re.escape(b)}\s*$", "", s)
        s = re.sub(rf"\s*{re.escape(b)}\s*", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


_RETAILER_CANON = {
    "ポケモンセンターオンライン": "pokemoncenter_online",
    "ポケモンセンター": "pokemoncenter",
    "ポケセン": "pokemoncenter",
    "ヨドバシ": "yodobashi",
    "ヨドバシ.com": "yodobashi",
    "ヨドバシカメラ": "yodobashi",
    "ビックカメラ": "biccamera",
    "ビック": "biccamera",
    "Amazon": "amazon",
    "アマゾン": "amazon",
    "楽天": "rakuten",
    "セブンネット": "seven_net",
    "セブン-イレブン": "seven_net",
    "TSUTAYA": "tsutaya",
    "駿河屋": "surugaya",
    "あみあみ": "amiami",
    "Joshin": "joshin",
    "ジョーシン": "joshin",
    "ヤマダデンキ": "yamada",
    "ヤマダ電機": "yamada",
}


def normalize_retailer(raw: str) -> str:
    s = _nfkc(raw).strip()
    for k, v in _RETAILER_CANON.items():
        if k in s:
            return v
    return re.sub(r"[^a-z0-9_]+", "_", s.lower()).strip("_") or "unknown"


def normalize_store(raw: str | None) -> str | None:
    if not raw:
        return None
    s = _nfkc(raw).translate(_BRACKETS)
    s = re.sub(r"^ポケモンセンター", "", s).strip()
    s = re.sub(r"\s+", " ", s).strip()
    return s or None
