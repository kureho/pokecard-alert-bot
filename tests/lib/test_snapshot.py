from datetime import datetime

from pokebot.lib.snapshot import content_hash, page_fingerprint


def test_whitespace_invariant():
    assert content_hash("hello  world") == content_hash("hello\n world")


def test_different_content_different_hash():
    assert content_hash("a") != content_hash("b")


def test_hash_is_32_hex():
    h = content_hash("x")
    assert len(h) == 32
    int(h, 16)


# ===== page_fingerprint (Dispatch1) =====


def test_page_fingerprint_is_32_hex():
    fp = page_fingerprint(title="アビスアイ抽選", retailer="pokemoncenter_online")
    assert len(fp) == 32
    int(fp, 16)


def test_page_fingerprint_differs_by_title():
    fp1 = page_fingerprint(title="アビスアイ抽選", retailer="x")
    fp2 = page_fingerprint(title="ジャッジメントズブスター抽選", retailer="x")
    assert fp1 != fp2


def test_page_fingerprint_stable_with_same_semantics():
    """同じ title/body/dates なら fingerprint は同一。"""
    args = dict(
        title="アビスアイ抽選",
        body_text="応募期間は 5/10 〜 5/14",
        apply_start_at=datetime(2026, 5, 10, 14),
        apply_end_at=datetime(2026, 5, 14, 23, 59),
        retailer="pokemoncenter_online",
        product_name_normalized="アビスアイ",
    )
    assert page_fingerprint(**args) == page_fingerprint(**args)


def test_page_fingerprint_whitespace_invariant_in_body():
    """body の空白差は影響しない (内容ベース)。"""
    fp1 = page_fingerprint(title="t", body_text="a  b\nc")
    fp2 = page_fingerprint(title="t", body_text="a b c")
    assert fp1 == fp2


def test_page_fingerprint_changes_with_apply_end():
    """応募期限の変更は fingerprint を変える (意味差分)。"""
    fp1 = page_fingerprint(
        title="t",
        apply_start_at=datetime(2026, 5, 10, 14),
        apply_end_at=datetime(2026, 5, 14, 23, 59),
    )
    fp2 = page_fingerprint(
        title="t",
        apply_start_at=datetime(2026, 5, 10, 14),
        apply_end_at=datetime(2026, 5, 20, 23, 59),
    )
    assert fp1 != fp2
