from __future__ import annotations

from ..models import Event, EventKind, Priority

_SOURCE_LABEL = {
    "yodobashi": "ヨドバシ.com",
    "bic": "ビックカメラ.com",
    "pokemon_center": "ポケモンセンターオンライン",
    "pokemon_card_news": "ポケモンカード公式",
    "pokeca_sokuhou": "ポケカ速報",
}


def _header(ev: Event) -> str:
    if ev.priority == Priority.CRITICAL and ev.kind == EventKind.LOTTERY_OPEN:
        return "🔥【BOX抽選開始】"
    if ev.priority == Priority.CRITICAL and ev.kind == EventKind.RESTOCK:
        return "🔥【BOX再販】"
    if ev.kind == EventKind.RESTOCK:
        return "🟢【再販】"
    if ev.kind == EventKind.NEW_PRODUCT:
        return "🟢【新商品情報】"
    return "📌【情報】"


def format_event(ev: Event) -> str:
    label = _SOURCE_LABEL.get(ev.source, ev.source)
    lines = [_header(ev), ev.product_name, f"▸ {label}"]
    if ev.lottery_deadline:
        lines.append(f"▸ 受付: 〜{ev.lottery_deadline.strftime('%m/%d %H:%M')}")
    if ev.price_yen:
        lines.append(f"▸ 価格: ¥{ev.price_yen:,}")
    lines.append(ev.url)
    return "\n".join(lines)


def format_aggregation(head: Event, additions: list[Event]) -> str:
    body = [f"📌【追加検知】{head.product_name}"]
    for a in additions:
        label = _SOURCE_LABEL.get(a.source, a.source)
        body.append(f"▸ {label} でも {a.kind.value}")
    body += [a.url for a in additions[:3]]
    return "\n".join(body)
