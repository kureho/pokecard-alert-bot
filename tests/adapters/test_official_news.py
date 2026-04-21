from pathlib import Path

import pytest

from pokebot.adapters.official_news import PokemonOfficialNewsAdapter
from pokebot.lib.title_classifier import TitleCategory


@pytest.mark.asyncio
async def test_no_body_fetch_irrelevant_filtered():
    """body_fetcher をモックして、大会/発売告知/結果発表が除外されることを確認。"""
    html = Path("tests/fixtures/pokemon_official_news.html").read_text(encoding="utf-8")

    async def _fake_fetcher(url):
        # 抽選情報なしのダミー本文 → RELEASE_ANNOUNCE は skip される
        return "<html><body><p>発売日: 5月22日</p></body></html>"

    adapter = PokemonOfficialNewsAdapter(
        html=html, body_fetcher=_fake_fetcher, max_body_fetch=20
    )
    candidates = await adapter.run()
    # 全 candidate の title_category が IRRELEVANT/CLOSED/RESULT でないことを確認
    for c in candidates:
        cat = c.extracted_payload.get("title_category")
        assert cat not in (
            str(TitleCategory.IRRELEVANT),
            str(TitleCategory.LOTTERY_CLOSED),
            str(TitleCategory.LOTTERY_RESULT),
        )


@pytest.mark.asyncio
async def test_body_info_applies_when_available():
    """body_fetcher が応募期間を含む html を返すと candidate の日時が埋まる。"""
    html = Path("tests/fixtures/pokemon_official_news.html").read_text(encoding="utf-8")

    async def _fake_fetcher(url):
        return (
            "<html><body>"
            "<p>応募期間: 2026年5月10日(土) 14:00 〜 2026年5月14日(水) 23:59</p>"
            "<p>結果発表: 2026年5月16日(金) 11:00</p>"
            "</body></html>"
        )

    adapter = PokemonOfficialNewsAdapter(
        html=html, body_fetcher=_fake_fetcher, max_body_fetch=20
    )
    candidates = await adapter.run()
    # 少なくとも1件は body_fetched=True + 日時ありであるはず
    bodied = [c for c in candidates if c.extracted_payload.get("body_fetched")]
    assert bodied
    assert any(c.apply_start_at is not None for c in bodied)


@pytest.mark.asyncio
async def test_official_news_adapter_name():
    assert PokemonOfficialNewsAdapter().source_name == "pokemon_official_news"
