from __future__ import annotations

import re
import unicodedata


def clean_text(raw: str) -> str:
    if not raw:
        return ""
    s = unicodedata.normalize("NFKC", raw)
    s = re.sub(r"[ \t\r\n\u3000]+", " ", s)
    return s.strip()


def extract_first_paragraph(raw: str, max_len: int = 300) -> str:
    s = clean_text(raw)
    return s[:max_len]
