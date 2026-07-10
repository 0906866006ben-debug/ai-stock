from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.app.research_platform.budget import OpenAIBudgetGuard
from backend.app.research_platform.repository import ResearchRepository
from backend.app.research_platform.strategy_dsl import PositionSizingRule, baseline_five_factor_v1

from .conftest import make_settings


def test_baseline_dsl_is_five_factor_and_has_invalidation() -> None:
    strategy = baseline_five_factor_v1()

    assert {factor.value for factor in strategy.core_factors} == {
        "FUNDING", "OPEN_INTEREST", "EMA", "VOLUME", "RSI"
    }
    assert "OPEN_INTEREST" in strategy.data_requirements
    assert strategy.entry_rule["completed_bars_only"] is True
    assert strategy.invalidation_signal
    assert strategy.position_sizing.risk_per_trade_pct == pytest.approx(0.25)


def test_position_risk_cannot_exceed_hard_limit() -> None:
    with pytest.raises(ValidationError, match="hard maximum"):
        PositionSizingRule(risk_per_trade_pct=0.5, hard_max_risk_per_trade_pct=0.25)


def test_openai_fails_closed_without_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    market_db: Path,
    runs_path: Path,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    settings = make_settings(tmp_path, market_db, runs_path)
    guard = OpenAIBudgetGuard(settings, ResearchRepository(settings.metadata_db_path))

    decision = guard.authorize("automatic", estimated_worst_cost_usd=0.5)

    assert decision.allowed is False
    assert decision.status == "DEFERRED_NOT_CONFIGURED"
    assert guard.summary().api_configured is False

