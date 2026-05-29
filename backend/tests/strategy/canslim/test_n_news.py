from __future__ import annotations

import asyncio

from backend.app.services import yahoo_news
from backend.app.services.strategy.canslim import live_screening
from backend.app.services.strategy.canslim import news_pillar
from backend.app.services.strategy.canslim.news_pillar import (
    NPillarAnalysis,
    NPillarClaim,
    _call_claude_n_pillar,
    _parse_json_object,
    _summarize_news_with_gemini,
    analyze_n_pillar_sources,
    analyze_n_pillar_sources_with_ai,
)
from backend.app.services.strategy.canslim.screening_language import contains_forbidden_action_language


async def test_yahoo_per_stock_fetch_maps_rows(monkeypatch):
    async def fake_fetch(query: str):
        assert "2330" in query
        return [{"title": "新產品發表", "url": "https://x/news", "published_at": "2026-05-10", "source": "鉅亨", "category": "industry"}]

    monkeypatch.setattr(yahoo_news, "_fetch_google_news_rss", fake_fetch)
    rows = await yahoo_news.get_tw_stock_news_yahoo("2330")
    assert rows and rows[0]["url"] == "https://x/news" and rows[0]["published_at"] == "2026-05-10"


async def test_n_deterministic_found_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    news = [{"title": "AI 新訂單放量", "url": "https://x/1", "published_at": "2026-05-10"}]
    out = await analyze_n_pillar_sources_with_ai(yahoo_news=news)
    assert out.evidence == "found"
    assert out.claims and out.claims[0].source_url == "https://x/1"
    assert not contains_forbidden_action_language(out.model_dump())


async def test_n_not_found_when_no_sources(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    out = await analyze_n_pillar_sources_with_ai(yahoo_news=[])
    assert out.evidence == "not_found"
    assert out.confidence == "low"
    assert not out.claims


def test_call_claude_returns_none_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = asyncio.run(_call_claude_n_pillar([{"source_url": "x", "published_date": "y", "summary": "z"}]))
    assert result is None


def test_parse_json_object_strips_fences_and_rejects_garbage():
    assert _parse_json_object('```json\n{"evidence": "not_found"}\n```') == {"evidence": "not_found"}
    assert _parse_json_object("not json at all") is None


def test_gemini_summary_returns_none_without_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    rows = [{"source_url": "https://x/1", "published_date": "2026-05-10", "summary": "headline"}]
    assert asyncio.run(_summarize_news_with_gemini(rows)) is None


async def test_catalyst_score_threads_through_ai_output():
    news = [{"title": "AI 新訂單放量", "url": "https://x/1", "published_at": "2026-05-10"}]
    ai = NPillarAnalysis(
        evidence="found",
        confidence="high",
        summary="sourced catalyst",
        claims=[NPillarClaim(source_url="https://x/1", published_date="2026-05-10", summary="AI 新訂單", catalyst_type="new_order")],
        catalyst_score=80,
    )
    out = analyze_n_pillar_sources(yahoo_news=news, ai_output=ai)
    assert out.catalyst_score == 80
    assert out.claims[0].catalyst_type == "new_order"


async def test_two_stage_pipeline_enriches_then_classifies(monkeypatch):
    calls = {"gemini": 0, "claude": 0}

    async def fake_gemini(sources):
        calls["gemini"] += 1
        return [
            {"source_url": s["source_url"], "published_date": s["published_date"], "summary": "factual note", "catalyst_type": "new_order"}
            for s in sources
        ]

    async def fake_claude(sources):
        calls["claude"] += 1
        assert sources[0]["summary"] == "factual note"  # Claude received Gemini-enriched rows
        return NPillarAnalysis(
            evidence="found",
            confidence="high",
            summary="classified",
            claims=[NPillarClaim(source_url=sources[0]["source_url"], published_date=sources[0]["published_date"], summary="AI 新訂單", catalyst_type="new_order")],
            catalyst_score=75,
        )

    monkeypatch.setattr(news_pillar, "_summarize_news_with_gemini", fake_gemini)
    monkeypatch.setattr(news_pillar, "_call_claude_n_pillar", fake_claude)
    news = [{"title": "some headline", "url": "https://x/1", "published_at": "2026-05-10"}]
    out = await analyze_n_pillar_sources_with_ai(yahoo_news=news)
    assert calls == {"gemini": 1, "claude": 1}
    assert out.catalyst_score == 75
    assert out.claims[0].catalyst_type == "new_order"


async def test_n_analysis_cache_prevents_recompute(monkeypatch):
    live_screening.clear_n_analysis_cache()
    calls = {"n": 0}

    async def fake_ai(**kwargs):
        calls["n"] += 1
        return NPillarAnalysis(evidence="not_found", confidence="low", summary="none", claims=[], data_warnings=[])

    monkeypatch.setattr(live_screening, "analyze_n_pillar_sources_with_ai", fake_ai)
    await live_screening._n_pillar_for("2330", "2026-05-21", [], [])
    await live_screening._n_pillar_for("2330", "2026-05-21", [], [])
    assert calls["n"] == 1  # second call served from cache
