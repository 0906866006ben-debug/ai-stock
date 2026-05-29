from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.services.backtest.metrics import PerformanceMetrics
from backend.app.services.backtest.signal_replay import CANSLIM_CANDIDATE_TYPE, ReplayConfig
from backend.app.services.strategy.canslim.walk_forward import (
    build_coarse_search_space,
    compute_wfe,
    discover_tunable_params,
    guard_candidate,
    grid_candidates,
    run_sensitivity,
    run_walk_forward,
    validate_search_space,
)
from backend.tests.strategy.canslim.test_phase_i1_backtest import (
    AS_OF,
    _canslim_store,
    _market,
    _strong_detail,
    _strong_fin,
    _weak_detail,
    _weak_fin,
)


def test_search_space_contains_only_tunable_params_and_rejects_frozen_param():
    tunables = discover_tunable_params()
    space = build_coarse_search_space()

    assert tunables == [
        "backtest.canslim.max_hold_days",
        "backtest.canslim.min_entry_grade",
        "scoring.grades.A_signal_min",
        "scoring.grades.B_signal_min",
    ]
    assert set(space) == set(tunables)
    assert "technical.rules.T-2.thresholds.close_to_high_252d_min" not in space
    with pytest.raises(ValueError, match="not tunable"):
        validate_search_space({"technical.rules.T-2.thresholds.close_to_high_252d_min": [0.95, 0.97, 0.99]})
    assert len(grid_candidates(space)) == 81


def test_degenerate_low_trade_candidate_is_rejected():
    metrics = PerformanceMetrics(
        n_trades=1,
        win_rate=1.0,
        avg_return=0.1,
        median_return=0.1,
        std_return=0.0,
        max_return=0.1,
        min_return=0.1,
        profit_factor=float("inf"),
        expectancy=0.1,
        sharpe=0.0,
        sortino=0.0,
        max_drawdown=0.0,
        avg_hold_days=5.0,
    )

    result = guard_candidate(metrics, min_trades=3)

    assert result.accepted is False
    assert "n_trades<3" in result.reasons
    assert "degenerate_unbounded_pf" in result.reasons


def test_wfe_computation_and_acceptance_threshold():
    assert compute_wfe(0.20, 0.12) == pytest.approx(0.6)
    assert compute_wfe(0.20, 0.05) < 0.5
    assert compute_wfe(0.0, 0.20) == 0.0


def test_sensitivity_perturbation_returns_stability_metric():
    params = {
        "backtest.canslim.min_entry_grade": "B",
        "backtest.canslim.max_hold_days": 30,
        "scoring.grades.A_signal_min": 55,
        "scoring.grades.B_signal_min": 35,
    }

    def evaluator(variant):
        penalty = abs(float(variant["scoring.grades.A_signal_min"]) - 55.0) / 100.0
        return 1.2 - penalty

    result = run_sensitivity(params, 1.2, evaluator)

    assert set(result) == {"base_sharpe", "worst_sharpe", "stability"}
    assert 0 <= result["stability"] <= 1
    assert result["worst_sharpe"] <= result["base_sharpe"]


def test_walk_forward_synthetic_completes_and_writes_report(tmp_path: Path):
    store = _canslim_store(tmp_path)
    params = {
        "backtest.canslim.min_entry_grade": "B",
        "backtest.canslim.max_hold_days": 30,
        "scoring.grades.A_signal_min": 55,
        "scoring.grades.B_signal_min": 35,
    }
    report = run_walk_forward(
        run_id="i2_synthetic",
        data_store=store,
        stock_universe=["STRONG", "WEAK"],
        windows=[("2024-09-10", "2024-09-12", "2024-09-13", AS_OF)],
        params=params,
        output_dir=tmp_path / "artifacts",
        replay_kwargs=_replay_kwargs(),
        min_trades=1,
    )

    assert Path(report.artifact_json).exists()
    assert Path(report.artifact_md).exists()
    assert len(report.windows) == 1
    assert report.windows[0].grade_distribution
    assert ReplayConfig(
        run_id="legacy",
        start_date=AS_OF,
        end_date=AS_OF,
        stock_universe=["STRONG"],
    ).target_candidate_types == ["起漲前觀察"]
    assert CANSLIM_CANDIDATE_TYPE != "起漲前觀察"


def _replay_kwargs() -> dict:
    return {
        "lookback_bars": 280,
        "canslim_market": _market(),
        "canslim_fin_metrics_by_stock": {
            "STRONG": _strong_fin(),
            "WEAK": _weak_fin(),
        },
        "canslim_detail_by_stock": {
            "STRONG": _strong_detail(),
            "WEAK": _weak_detail(),
        },
        "canslim_universe_returns_60d": {"STRONG": 0.8, "WEAK": 0.1},
        "canslim_universe_returns_252d": {"STRONG": 0.8, "WEAK": 0.1},
        "canslim_eps_filing_dates_by_stock": {"STRONG": "2024-09-01", "WEAK": "2024-09-01"},
        "canslim_event_window_by_stock": {"STRONG": False, "WEAK": False},
    }
