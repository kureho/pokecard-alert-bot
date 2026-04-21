from __future__ import annotations

import hashlib
from datetime import datetime


def content_hash(text: str) -> str:
    """Normalize whitespace before hashing to be resilient to trivial reformatting."""
    norm = " ".join(text.split())
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:32]


def page_fingerprint(
    *,
    title: str,
    body_text: str | None = None,
    apply_start_at: datetime | None = None,
    apply_end_at: datetime | None = None,
    result_at: datetime | None = None,
    retailer: str = "",
    product_name_normalized: str = "",
) -> str:
    """本文ベースの fingerprint。URL の query 変動に依存しない安定キー。

    title + body 先頭抜粋 + dates + retailer + product を正規化連結して sha256。
    同一の告知でも URL の utm param が変わるだけで別ページ扱いになるのを避ける。
    """
    parts = [
        " ".join(title.split())[:200] if title else "",
        " ".join(body_text.split())[:300] if body_text else "",
        apply_start_at.strftime("%Y%m%dT%H%M") if apply_start_at else "-",
        apply_end_at.strftime("%Y%m%dT%H%M") if apply_end_at else "-",
        result_at.strftime("%Y%m%dT%H%M") if result_at else "-",
        retailer or "-",
        product_name_normalized or "-",
    ]
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
