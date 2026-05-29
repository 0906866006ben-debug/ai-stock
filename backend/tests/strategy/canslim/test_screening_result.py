from __future__ import annotations

from types import SimpleNamespace

from backend.app.services.strategy.canslim import screening
from backend.app.services.strategy.canslim.types import HorizonObservation, MarketFeatures


def _card(
    *,
    grade: str = "A",
    triggered: list[str] | None = None,
    warnings: list[str] | None = None,
    hard_blocked: bool = False,
    blocking: list[str] | None = None,
) -> HorizonObservation:
    return HorizonObservation(
        horizon="swing_term",
        status="watching",
        direction_hint="up",
        evidence_based_reasons=["G-1 revenue condition aligned", "T-1 relative strength condition aligned"],
        triggered_rule_ids=triggered or ["G-1", "G-2", "T-1", "T-2", "SD-1", "I-1", "M-1", "M-2", "M-3"],
        suitable_strategy_examples=[],
        key_observation_conditions=[],
        invalidation_signals=[],
        risk_level="moderate",
        confidence_level="high",
        scores={
            "grade": grade,
            "signal": 65,
            "risk": 20,
            "confidence": 80,
            "hard_blocked": hard_blocked,
            "blocking_rule_ids": blocking or [],
        },
        data_warnings=warnings or [],
    )


def test_observe_maps_to_screening_result(monkeypatch):
    monkeypatch.setattr(screening, "build_market_features", lambda *args, **kwargs: MarketFeatures())
    monkeypatch.setattr(screening, "regime_severity", lambda *args, **kwargs: "risk_on")
    monkeypatch.setattr(screening, "observe", lambda *args, **kwargs: {"swing_term": _card()})

    result = screening.build_screening_result("2330", "2024-01-02", store=object())

    assert result.stock_id == "2330"
    assert result.candidate_grade == "A"
    assert result.market_regime == "risk_on"
    assert result.pillars["C"] == "Pass"
    assert result.pillars["N"] == "AI_Review_Required"
    assert result.canslim_match.endswith("/7")
    assert result.action_type == "Manual Review Required"


def test_screening_result_strings_are_verb_free(monkeypatch):
    monkeypatch.setattr(screening, "build_market_features", lambda *args, **kwargs: MarketFeatures())
    monkeypatch.setattr(screening, "regime_severity", lambda *args, **kwargs: "risk_on")
    monkeypatch.setattr(
        screening,
        "observe",
        lambda *args, **kwargs: {
            "swing_term": _card(triggered=["G-1", "T-1"], warnings=["target price missing; buy/sell language avoided"])
        },
    )

    result = screening.build_screening_result("2330", "2024-01-02", store=object())

    assert not screening.contains_forbidden_action_language(result.model_dump())


def test_severe_regime_downgrades_grade_and_action_type(monkeypatch):
    monkeypatch.setattr(screening, "build_market_features", lambda *args, **kwargs: MarketFeatures())
    monkeypatch.setattr(screening, "regime_severity", lambda *args, **kwargs: "severe")
    monkeypatch.setattr(screening, "observe", lambda *args, **kwargs: {"swing_term": _card(grade="S")})

    result = screening.build_screening_result("2330", "2024-01-02", store=object())

    assert result.candidate_grade == "B"
    assert result.market_regime == "severe"
    assert result.pillars["M"] == "Fail"
    assert result.action_type == "Manual Review Required"


def test_missing_data_pillars_mark_manual_review(monkeypatch):
    monkeypatch.setattr(screening, "build_market_features", lambda *args, **kwargs: MarketFeatures(data_warnings=["TAIEX index data missing"]))
    monkeypatch.setattr(screening, "regime_severity", lambda *args, **kwargs: None)
    # Genuine no-data scenario (no fundamentals, no OHLCV) so C/A/I are Insufficient.
    # Forced here so the test does not depend on a live fetch for the real symbol.
    monkeypatch.setattr(screening, "_features_and_rule_results", lambda *args, **kwargs: (None, {}))
    monkeypatch.setattr(
        screening,
        "observe",
        lambda *args, **kwargs: {
            "swing_term": _card(
                grade="B",
                triggered=[],
                warnings=["EPS filing data missing", "foreign institution input missing"],
            )
        },
    )

    result = screening.build_screening_result("2330", "2024-01-02", store=object())

    assert result.market_regime == "unknown"
    assert result.pillars["C"] == "Insufficient_Data"
    assert result.pillars["I"] == "Insufficient_Data"
    assert result.pillars["M"] == "Insufficient_Data"
    assert "C pillar data gap" in result.needs_manual_review
    assert "I pillar data gap" in result.needs_manual_review
