from pathlib import Path

import pytest
from pokebot.config import load_sources
from pokebot.monitors.feed import FeedMonitor
from pokebot.monitors.html import HtmlMonitor


def test_load_sources_returns_only_enabled():
    monitors = load_sources(Path("tests/fixtures/sources_ok.yaml"))
    ids = [m.id for m in monitors]
    assert "yodobashi_lottery" in ids
    assert "pokeca_sokuhou_rss" in ids
    assert "disabled_one" not in ids


def test_load_sources_dispatches_monitor_type():
    monitors = load_sources(Path("tests/fixtures/sources_ok.yaml"))
    by_id = {m.id: m for m in monitors}
    assert isinstance(by_id["yodobashi_lottery"], HtmlMonitor)
    assert isinstance(by_id["pokeca_sokuhou_rss"], FeedMonitor)
    assert by_id["yodobashi_lottery"].interval_sec == 120


def test_load_sources_raises_on_unknown_parser(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "sources:\n"
        "  - id: x\n    kind: html\n    url: https://x\n"
        "    interval_sec: 60\n    parser: nonexistent.parser\n    enabled: true\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="parser"):
        load_sources(bad)


def test_load_sources_raises_on_unknown_kind(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "sources:\n"
        "  - id: x\n    kind: nope\n    url: https://x\n"
        "    interval_sec: 60\n    parser: yodobashi.lottery_list\n    enabled: true\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="kind"):
        load_sources(bad)
