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

# 既知商品辞書 (現在〜近い過去の Pokemon TCG 拡張パック/BOX 商品名)
# NOTE: テキスト内に辞書単語が含まれれば、それを一意の商品名として返す。
#       normalize_product_name より優先。店舗ごとに body の書き方が違っても
#       同じ product_name_normalized に収束させるための辞書。
# 追加/更新ルール:
#   - 短いサブストリングを後ろに並べる (最長マッチ優先)
#   - 表記ゆれ (MEGA vs メガ, ex vs EX 等) は両方登録する
KNOWN_PRODUCTS: list[str] = [
    # MEGA 拡張パック系 (2026 春〜)
    "MEGAドリームex",
    "メガドリームex",
    "メガブレイブ",
    "メガシンフォニア",
    "アビスアイ",
    "ニンジャスピナー",
    "ムニキスゼロ",
    # 拡張パック (SV 世代)
    "テラスタルフェスex",
    "シャイニートレジャーex",
    "熱風のアリーナ",
    "ロケット団の栄光",
    "ブラックボルト",
    "ホワイトフレア",
    "インフェルノX",
    "ダークファンタズマ",
    "ポケモンカード151",
    "クレイバースト",
    "VSTARユニバース",
    # テーマ商品
    "PIKACHU DINER",
]

# 日付パターン (X月Y日 / X/Y / 曜日表記)
_DATE_PATTERNS = [
    re.compile(r"\d{4}年\d{1,2}月\d{1,2}日(?:\([月火水木金土日]\)|（[月火水木金土日]）)?"),
    re.compile(r"\d{1,2}月\d{1,2}日(?:\([月火水木金土日]\)|（[月火水木金土日]）)?"),
    re.compile(r"\d{1,2}/\d{1,2}(?:\([月火水木金土日]\)|（[月火水木金土日]）)?"),
]

# 商品名モディファイア (ブランド付随要素)
_MODIFIERS = [
    "MEGA", "Mega", "mega",
    "S&V", "S＆V",
    "VSTAR", "VMAX", "V-UNION", "GX",
]

# Suffix phrase (情報種別を示す接尾句)
_SUFFIX_PHRASES = [
    "抽選予約販売", "抽選予約・販売", "抽選予約", "抽選販売",
    "予約販売", "抽選",
    "販売のお知らせ", "販売予定", "発売のお知らせ",
    "のお知らせ", "について",
    "受付開始", "発売決定", "発売予定", "発売日", "発売",
    "予約受付", "予約", "情報", "案内", "の案内",
]

# 内容を示さない修飾ワード
_DECOR_WORDS = [
    "新弾", "新商品", "商品", "関連商品",
]


def _nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", s)


def extract_known_product_name(text: str) -> str | None:
    """テキスト内に既知商品名が含まれれば、それを返す (複数マッチ時は最長優先)。

    Examples:
      「5月22日発売 MEGA アビスアイ抽選予約」 → "アビスアイ"
      「MEGAドリームex 抽選販売」 → "MEGAドリームex" (ドリーム より長い)
    """
    if not text:
        return None
    s = _nfkc(text)
    matches: list[str] = []
    for name in KNOWN_PRODUCTS:
        if name in s:
            matches.append(name)
    if not matches:
        return None
    # 最長マッチ優先 (重複要素があっても max は 1 つ返す)
    return max(matches, key=len)


def normalize_product_name(raw: str) -> str:
    """Strip brand/type/form/date/modifier decorators and return core product identifier.

    優先順:
      1. 既知商品辞書マッチ → それを返す (店舗ごとの body ゆれを無効化)
      2. 日付・brand prefix・type prefix・modifier・form suffix・suffix phrase を削除

    Examples:
      アビスアイ / 拡張パック アビスアイ / ポケモンカードゲーム 拡張パック アビスアイ BOX
        → アビスアイ
      「5月22日発売 MEGA 拡張パック アビスアイ抽選予約販売のお知らせ」
        → アビスアイ (辞書マッチ)
    """
    if not raw:
        return ""

    # 1. 既知商品辞書マッチ優先
    known = extract_known_product_name(raw)
    if known:
        return known

    # 2. decorator 除去 fallback
    s = _nfkc(raw).translate(_BRACKETS)
    s = re.sub(r"\s+", " ", s).strip()

    # 日付パターンを削除
    for pat in _DATE_PATTERNS:
        s = pat.sub(" ", s)

    # Brand prefix 削除 (先頭 + 中間)
    for p in _BRAND_PREFIXES:
        s = re.sub(rf"^{re.escape(p)}\s*", "", s)
        s = re.sub(rf"\s*{re.escape(p)}\s*", " ", s)

    # Type prefix 削除 (先頭 + 中間)
    for p in _TYPE_PREFIXES:
        s = re.sub(rf"^{re.escape(p)}\s*", "", s)
        s = re.sub(rf"\s*{re.escape(p)}\s*", " ", s)

    # Modifier (MEGA, SV, VSTAR 等) 削除
    for m in _MODIFIERS:
        s = re.sub(rf"(?:^|\s){re.escape(m)}(?=\s|$)", " ", s)

    # Form suffix (BOX, ボックス, 1BOX 等) 削除
    for b in _FORM_SUFFIXES:
        s = re.sub(rf"\s*{re.escape(b)}\s*$", "", s)
        s = re.sub(rf"\s*{re.escape(b)}\s*", " ", s)

    # Decor words 削除
    for w in _DECOR_WORDS:
        s = re.sub(rf"(?:^|\s){re.escape(w)}(?=\s|$)", " ", s)

    # Suffix phrase (抽選販売、お知らせ 等) 削除
    for phrase in _SUFFIX_PHRASES:
        s = re.sub(rf"\s*{re.escape(phrase)}\s*", " ", s)

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
