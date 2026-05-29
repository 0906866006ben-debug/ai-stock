from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.app.services.strategy.canslim import screening
from backend.app.services.strategy.canslim.news_pillar import NPillarAnalysis, NPillarClaim, analyze_n_pillar_sources
from backend.app.services.strategy.canslim.types import HorizonObservation, MarketFeatures


def _card() -> HorizonObservation:
    return HorizonObservation(
        horizon="swing_term",
        status="watching",
        direction_hint="up",
        evidence_based_reasons=["G-1 revenue condition aligned", "T-1 relative strength condition aligned"],
        triggered_rule_ids=["G-1", "G-2", "T-1", "T-2", "SD-1", "I-1", "M-1", "M-2"],
        suitable_strategy_examples=[],
        key_observation_conditions=[],
        invalidation_signals=[],
        risk_level="moderate",
        confidence_level="high",
        scores={"grade": "A", "signal": 65, "risk": 20, "confidence": 80, "hard_blocked": False},
        data_warnings=[],
    )


def test_n_pillar_output_schema_requires_sources() -> None:
    with pytest.raises(ValidationError):
        NPillarAnalysis(
            evidence="found",
            confidence="moderate",
            summary="N pillar has evidence.",
            claims=[{"source_url": "", "published_date": "2026-01-01", "summary": "valid text"}],
        )


def test_no_source_input_returns_not_found_low_confidence() -> None:
    result = analyze_n_pillar_sources(yahoo_news=[], tw_news_sentiment=[], calendar=[])

    assert result.evidence == "not_found"
    assert result.confidence == "low"
    assert result.claims == []


def test_n_pillar_is_verb_free_and_uses_only_supplied_sources() -> None:
    result = analyze_n_pillar_sources(
        yahoo_news=[
            {
                "title": "公司公布新產品進度",
                "url": "https://example.com/news/1",
                "published_at": "2026-01-02",
            }
        ],
        ai_output={
            "evidence": "found",
            "confidence": "high",
            "summary": "buy wording should be cleaned",
            "claims": [
                {
                    "source_url": "https://example.com/news/1",
                    "published_date": "2026-01-02",
                    "summary": "公司公布新產品進度",
                },
                {
                    "source_url": "https://example.com/fabricated",
                    "published_date": "2026-01-03",
                    "summary": "fabricated catalyst",
                },
            ],
        },
    )

    assert result.evidence == "found"
    assert len(result.claims) == 1
    assert result.claims[0].source_url == "https://example.com/news/1"
    assert not screening.contains_forbidden_action_language(result.model_dump())


def test_screening_result_replaces_n_placeholder_when_sourced_evidence_exists(monkeypatch) -> None:
    monkeypatch.setattr(screening, "build_market_features", lambda *args, **kwargs: MarketFeatures())
    monkeypatch.setattr(screening, "regime_severity", lambda *args, **kwargs: "risk_on")
    monkeypatch.setattr(screening, "observe", lambda *args, **kwargs: {"swing_term": _card()})

    result = screening.build_screening_result(
        "2330",
        "2026-01-02",
        store=object(),
        yahoo_news=[
            {
                "title": "公司公布新產品進度",
                "url": "https://example.com/news/1",
                "published_at": "2026-01-02",
            }
        ],
    )

    # Hybrid N policy: sourced news is recognized and attached as evidence, but with
    # no verifiable 52-week-high price data it does NOT Pass on news alone — the
    # new-high price backbone must confirm. It is held (Weak / AI_Review_Required).
    assert result.pillars["N"] in {"Weak", "AI_Review_Required"}
    assert any(item.pillar == "N" and item.source_url and item.published_date for item in result.evidence)
    assert not screening.contains_forbidden_action_language(result.model_dump())


def test_n_claim_rejects_prediction_language() -> None:
    with pytest.raises(ValidationError):
        NPillarClaim(
            source_url="https://example.com/news/1",
            published_date="2026-01-02",
            summary="target price and will rise language",
        )
