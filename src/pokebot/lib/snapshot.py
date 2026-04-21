from __future__ import annotations

import hashlib


def content_hash(text: str) -> str:
    """Normalize whitespace before hashing to be resilient to trivial reformatting."""
    norm = " ".join(text.split())
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:32]
