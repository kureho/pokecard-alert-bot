from pokebot.lib.snapshot import content_hash


def test_whitespace_invariant():
    assert content_hash("hello  world") == content_hash("hello\n world")


def test_different_content_different_hash():
    assert content_hash("a") != content_hash("b")


def test_hash_is_32_hex():
    h = content_hash("x")
    assert len(h) == 32
    int(h, 16)
