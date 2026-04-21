from pathlib import Path

import pytest

from pokebot.adapters.rakuten_books_entry import (
    RakutenBooksEntryAdapter,
    _extract_period,
    _extract_result_date,
)


def test_extract_period_parses_accepting_format():
    text = (
        "抽選受付期間 2026/1/23（金） 10：00 ～ 2026/1/26（月） 11：59 当選連絡予定日"
    )
    start, end = _extract_period(text)
    assert start is not None and start.year == 2026
    assert start.month == 1 and start.day == 23 and start.hour == 10
    assert end is not None and end.day == 26 and end.hour == 11 and end.minute == 59


def test_extract_result_date():
    text = "当選連絡予定日:2026/2/6(金)頃"
    r = _extract_result_date(text)
    assert r is not None
    assert r.year == 2026 and r.month == 2 and r.day == 6


def test_extract_period_returns_none_if_absent():
    assert _extract_period("無関係なテキスト") == (None, None)


@pytest.mark.asyncio
async def test_rakuten_adapter_on_ended_fixture():
    # fixture は受付終了状態。終了でも candidate 1つ返ることを確認。
    # fixture は EUC-JP なので、test 側で明示 decode して adapter に inject する。
    raw = Path("tests/fixtures/rakuten_books_entry.html").read_bytes()
    html = raw.decode("euc-jp", errors="replace")
    adapter = RakutenBooksEntryAdapter(html=html)
    candidates = await adapter.run()
    assert len(candidates) == 1
    c = candidates[0]
    assert c.retailer_name == "rakuten_books"
    assert c.evidence_type == "entry_page"
    assert c.sale_status_hint == "ended"
    assert c.apply_start_at is not None
    assert c.apply_end_at is not None
    assert c.result_at is not None
    assert c.source_url.endswith("/event/game/card/entry/")
    assert c.application_url == c.source_url


@pytest.mark.asyncio
async def test_rakuten_adapter_on_accepting_synthetic():
    html = """<html><body>
    <div>ポケモンカードゲーム 抽選販売の 受付中です。</div>
    <div>抽選受付期間 2026/5/1（金） 10：00 ～ 2026/5/4（月） 11：59</div>
    <div>当選連絡予定日:2026/5/16(金)頃</div>
    </body></html>"""
    adapter = RakutenBooksEntryAdapter(html=html)
    candidates = await adapter.run()
    assert len(candidates) == 1
    c = candidates[0]
    assert c.sale_status_hint == "accepting"
    assert c.apply_start_at is not None and c.apply_start_at.month == 5
    assert c.apply_end_at is not None and c.apply_end_at.day == 4
    assert c.result_at is not None and c.result_at.day == 16


@pytest.mark.asyncio
async def test_rakuten_adapter_empty_body_returns_nothing():
    adapter = RakutenBooksEntryAdapter(html="<html><body></body></html>")
    candidates = await adapter.run()
    assert candidates == []
