from types import MappingProxyType

import pytest
import yaml
from pydantic import ValidationError

from backend.app.services.strategy.canslim.params import load_params
from backend.app.services.strategy.canslim.types import HorizonObservation, RuleResult


def test_yaml_loads_and_has_meta():
    with open("backend/data/strategy/canslim_thresholds_v1.yaml", "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)

    assert data["meta"]["version"] == "v1"
    assert data["meta"]["tuning_required"] is True


def test_params_loader_returns_pillars():
    params = load_params()
    cached = load_params()

    assert params is cached
    assert isinstance(params, MappingProxyType)
    for key in (
        "meta",
        "growth",
        "technical",
        "supply",
        "institutional",
        "market",
        "risk",
        "base_geometry",
        "scoring",
        "backtest",
    ):
        assert key in params

    with pytest.raises(TypeError):
        params["meta"] = {}


def test_types_instantiate():
    rule = RuleResult(rule_id="G-1", triggered=True, signal_delta=15)
    assert rule.rule_id == "G-1"
    assert rule.triggered is True

    observation = HorizonObservation(
        horizon="swing_term",
        status="watching",
        direction_hint="up",
        evidence_based_reasons=["[G-1] revenue acceleration evidence"],
        triggered_rule_ids=["G-1"],
        suitable_strategy_examples=["observe pullback quality"],
        key_observation_conditions=["confirm volume behavior"],
        invalidation_signals=["revenue growth weakens"],
        risk_level="moderate",
        confidence_level="high",
        scores={"signal": 15, "risk": 0, "confidence": 60},
        data_warnings=[],
    )
    assert observation.horizon == "swing_term"
    assert observation.triggered_rule_ids == ["G-1"]

    with pytest.raises(ValidationError):
        HorizonObservation(
            horizon="intraday",
            status="watching",
            direction_hint="up",
            risk_level="moderate",
            confidence_level="high",
        )

