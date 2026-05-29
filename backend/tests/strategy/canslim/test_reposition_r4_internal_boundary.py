from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.services.strategy.canslim import screening
from backend.app.services.strategy.canslim.types import HorizonObservation, MarketFeatures

FORBIDDEN_USER_SURFACE_KEYS = {
    "trade_simulator",
    "optimizer",
    "position_multiplier",
    "position_multipliers",
    "tier_position_multipliers",
    "entry_tier",
    "min_entry_tier",
}


def _card() -> HorizonObservation:
    return HorizonObservation(
        horizon="swing_term",
        status="watching",
        direction_hint="up",
        evidence_based_reasons=["G-1 revenue condition aligned"],
        triggered_rule_ids=["G-1", "G-2", "T-1", "SD-1", "I-1", "M-1"],
        suitable_strategy_examples=[],
        key_observation_conditions=[],
        invalidation_signals=[],
        risk_level="moderate",
        confidence_level="high",
        scores={"grade": "B", "signal": 50, "risk": 20, "confidence": 70, "hard_blocked": False},
        data_warnings=[],
    )


def _contains_forbidden_key(value) -> bool:
    if isinstance(value, dict):
        return any(str(key) in FORBIDDEN_USER_SURFACE_KEYS or _contains_forbidden_key(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_forbidden_key(item) for item in value)
    return False


def test_analyze_tw_user_surface_has_no_internal_backtest_fields(monkeypatch) -> None:
    from backend.app.main import app

    monkeypatch.delenv("FINMIND_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    client = TestClient(app)

    response = client.get("/analyze/tw", params={"symbol": "2330", "include_canslim": True})

    assert response.status_code == 200
    assert not _contains_forbidden_key(response.json())


def test_screening_result_has_no_internal_backtest_fields(monkeypatch) -> None:
    monkeypatch.setattr(screening, "build_market_features", lambda *args, **kwargs: MarketFeatures())
    monkeypatch.setattr(screening, "regime_severity", lambda *args, **kwargs: "risk_on")
    monkeypatch.setattr(screening, "observe", lambda *args, **kwargs: {"swing_term": _card()})

    result = screening.build_screening_result("2330", "2026-01-02", store=object())

    assert not _contains_forbidden_key(result.model_dump())
    assert not screening.contains_forbidden_action_language(result.model_dump())


def test_backtest_modules_remain_importable_as_internal_validation() -> None:
    from backend.app.services.backtest import trade_simulator
    from backend.app.services.backtest.v1 import optimizer

    assert hasattr(trade_simulator, "simulate_trades")
    assert hasattr(optimizer, "run_optimization")
