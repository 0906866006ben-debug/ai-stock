"""Tests for the strategy parameter optimizer."""
from __future__ import annotations

import os
import random
import tempfile
from pathlib import Path

import pandas as pd
import pytest

from backend.app.services.backtest.optimizer import (
    OBJECTIVE_FORMULA,
    _adaptive_batch_size,
    apply_override,
    build_adaptive_value_weights,
    clear_override,
    compute_convergence_summary,
    compute_dimension_analysis,
    compute_objective,
    compute_split_metrics,
    deep_merge,
    derive_recommendation,
    estimate_grid_size,
    expand_dotted,
    grid_iterator,
    load_search_space,
    params_hash,
    sample_params_weighted,
    sample_unique_params,
    sample_params_random,
    split_dates,
    write_best_params,
    write_best_summary,
    write_runs_csv,
    write_summary_for_llm,
    write_validation_report,
)
from backend.app.services.backtest.optimizer_config import (
    CategoryMetrics,
    GateConfig,
    OptimizerConfig,
    SplitMetrics,
    TrialResult,
    detect_overfit,
    gates_passed_count,
)
from backend.app.services.screener_rules import load_surge_candidate_rules


# ───────────────────────────────────────────────────────────────────────────
# 1. Parameter sampling
# ───────────────────────────────────────────────────────────────────────────

def test_random_sampling_covers_all_dimensions():
    space = {
        "a.b": [1, 2, 3],
        "c": [10, 20],
        "d.e.f": [100, 200, 300, 400],
    }
    rng = random.Random(0)
    samples = [sample_params_random(space, rng) for _ in range(200)]
    assert all(set(s.keys()) == set(space.keys()) for s in samples)
    # All values from each dim should appear at least once in 200 random draws
    for key, values in space.items():
        seen = {s[key] for s in samples}
        assert seen <= set(values)


def test_expand_dotted_builds_nested_dict():
    flat = {
        "price_position.min_return_60d": -0.10,
        "ema.pre_breakout_ema_spread_max": 0.03,
        "classification.pre_breakout_score_min": 60,
    }
    nested = expand_dotted(flat)
    assert nested["price_position"]["min_return_60d"] == -0.10
    assert nested["ema"]["pre_breakout_ema_spread_max"] == 0.03
    assert nested["classification"]["pre_breakout_score_min"] == 60


def test_params_hash_is_deterministic_and_order_invariant():
    p1 = {"a": 1, "b": 2, "c": 3}
    p2 = {"c": 3, "a": 1, "b": 2}
    assert params_hash(p1) == params_hash(p2)
    p3 = {"a": 1, "b": 2, "c": 4}
    assert params_hash(p1) != params_hash(p3)


# ───────────────────────────────────────────────────────────────────────────
# 2. Deep merge
# ───────────────────────────────────────────────────────────────────────────

def test_deep_merge_preserves_unmodified_keys():
    base = {"a": {"b": 1, "c": 2}, "d": 3}
    over = {"a": {"b": 99}}
    out = deep_merge(base, over)
    assert out == {"a": {"b": 99, "c": 2}, "d": 3}
    # input not mutated
    assert base == {"a": {"b": 1, "c": 2}, "d": 3}


# ───────────────────────────────────────────────────────────────────────────
# 3. Gate evaluation
# ───────────────────────────────────────────────────────────────────────────

def test_gates_passed_count_matches_thresholds():
    gates = GateConfig(min_trades=30, min_win_rate=0.45, min_profit_factor=1.05, max_drawdown_pct=-0.15)
    # All pass
    m = SplitMetrics(n_trades=50, win_rate=0.60, profit_factor=1.5, max_drawdown=-0.10)
    assert gates_passed_count(m, gates) == 4
    # n_trades fails
    m2 = SplitMetrics(n_trades=10, win_rate=0.60, profit_factor=1.5, max_drawdown=-0.10)
    assert gates_passed_count(m2, gates) == 3
    # All fail
    m3 = SplitMetrics(n_trades=5, win_rate=0.30, profit_factor=0.8, max_drawdown=-0.30)
    assert gates_passed_count(m3, gates) == 0


def test_tiny_no_loss_sample_does_not_pass_profit_factor_gate():
    gates = GateConfig(min_trades=3, min_win_rate=0.45, min_profit_factor=1.05, max_drawdown_pct=-0.15)
    thin_no_loss = SplitMetrics(n_trades=5, win_rate=1.0, profit_factor=999.0, max_drawdown=0.0)

    # Passes trade count / win rate / drawdown, but PF=999 is undefined with
    # too few trades and must not count as a robust PF gate.
    assert gates_passed_count(thin_no_loss, gates) == 3


# ───────────────────────────────────────────────────────────────────────────
# 4. Objective scoring
# ───────────────────────────────────────────────────────────────────────────

def test_objective_higher_for_better_validation():
    config = OptimizerConfig(target="cat3")
    weak = SplitMetrics(n_trades=30, win_rate=0.40, avg_return_pct=0.005, profit_factor=1.0, max_drawdown=-0.10, expectancy=0.001, gates_passed=1)
    strong = SplitMetrics(n_trades=30, win_rate=0.70, avg_return_pct=0.04, profit_factor=2.5, max_drawdown=-0.08, expectancy=0.025, gates_passed=4)
    train = SplitMetrics(n_trades=30, win_rate=0.65, avg_return_pct=0.04, profit_factor=2.2, max_drawdown=-0.10, expectancy=0.022, gates_passed=4)

    score_weak = compute_objective(train, weak, config)
    score_strong = compute_objective(train, strong, config)
    assert score_strong > score_weak


def test_objective_penalizes_overfit_train_val_gap():
    config = OptimizerConfig(target="cat3")
    val = SplitMetrics(n_trades=30, win_rate=0.50, avg_return_pct=0.01, profit_factor=1.2, max_drawdown=-0.10, expectancy=0.005, gates_passed=2)
    train_aligned = SplitMetrics(n_trades=30, win_rate=0.55, avg_return_pct=0.012, profit_factor=1.3, max_drawdown=-0.10, expectancy=0.006, gates_passed=2)
    train_overfit = SplitMetrics(n_trades=30, win_rate=0.90, avg_return_pct=0.08, profit_factor=4.0, max_drawdown=-0.05, expectancy=0.04, gates_passed=4)

    aligned_score = compute_objective(train_aligned, val, config)
    overfit_score = compute_objective(train_overfit, val, config)
    assert aligned_score > overfit_score  # overfit pair gets penalized


def test_objective_hard_rejects_tiny_no_loss_profit_factor():
    config = OptimizerConfig(target="cat3", gates=GateConfig(min_trades=3))
    train = SplitMetrics(n_trades=20, win_rate=0.5, avg_return_pct=0.01, profit_factor=1.2, max_drawdown=-0.10, expectancy=0.005, gates_passed=2)
    val = SplitMetrics(n_trades=5, win_rate=1.0, avg_return_pct=0.04, profit_factor=999.0, max_drawdown=0.0, expectancy=0.04, gates_passed=3)

    assert compute_objective(train, val, config) == -2000.0


# ───────────────────────────────────────────────────────────────────────────
# 5. Overfit detection
# ───────────────────────────────────────────────────────────────────────────

def test_overfit_warning_triggers_on_wr_gap():
    train = SplitMetrics(n_trades=30, win_rate=0.85, avg_return_pct=0.03, profit_factor=2.0, max_drawdown=-0.08)
    val = SplitMetrics(n_trades=10, win_rate=0.40, avg_return_pct=0.01, profit_factor=1.0, max_drawdown=-0.10)
    warning, _ = detect_overfit(train, val)
    assert warning is True


def test_overfit_warning_quiet_when_aligned():
    train = SplitMetrics(n_trades=30, win_rate=0.60, avg_return_pct=0.02, profit_factor=1.5, max_drawdown=-0.10)
    val = SplitMetrics(n_trades=12, win_rate=0.58, avg_return_pct=0.018, profit_factor=1.45, max_drawdown=-0.11)
    warning, _ = detect_overfit(train, val)
    assert warning is False


# ───────────────────────────────────────────────────────────────────────────
# 6. Chronological split
# ───────────────────────────────────────────────────────────────────────────

def test_split_dates_no_overlap_and_proportional():
    dates = [f"2024-{m:02d}-{d:02d}" for m in [1, 2, 3] for d in [1, 8, 15, 22]]
    train, val = split_dates(dates, 0.75)
    assert len(train) + len(val) == len(dates)
    assert train[-1] < val[0]
    assert len(train) == 9  # 75% of 12


# ───────────────────────────────────────────────────────────────────────────
# 7. Env var override + cache invalidation
# ───────────────────────────────────────────────────────────────────────────

def test_env_var_override_invalidates_rules_cache(tmp_path: Path):
    base = load_surge_candidate_rules()
    base_min = base["classification"]["pre_breakout_score_min"]

    # Write override pointing to a different value
    override_value = base_min + 7
    override_path = tmp_path / "override.yaml"
    import yaml
    override_payload = {"surge_candidate": dict(base)}
    override_payload["surge_candidate"]["classification"] = dict(base["classification"])
    override_payload["surge_candidate"]["classification"]["pre_breakout_score_min"] = override_value
    with override_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(override_payload, f, allow_unicode=True)

    try:
        apply_override(override_path)
        refreshed = load_surge_candidate_rules()
        assert refreshed["classification"]["pre_breakout_score_min"] == override_value
    finally:
        clear_override()

    # Back to baseline after clear
    restored = load_surge_candidate_rules()
    assert restored["classification"]["pre_breakout_score_min"] == base_min


# ───────────────────────────────────────────────────────────────────────────
# 8. Grid sizing safeguard
# ───────────────────────────────────────────────────────────────────────────

def test_grid_size_estimation():
    space = {"a": [1, 2, 3], "b": [10, 20], "c": [100, 200, 300, 400]}
    assert estimate_grid_size(space) == 3 * 2 * 4

    grid = list(grid_iterator(space))
    assert len(grid) == 24


# ───────────────────────────────────────────────────────────────────────────
# 9. Compute split metrics from trades DataFrame
# ───────────────────────────────────────────────────────────────────────────

def test_compute_split_metrics_aggregates_per_category():
    trades = pd.DataFrame([
        {"entry_status": "filled", "net_return_pct": 0.10, "hold_days": 5, "exit_date": "2024-01-05", "sector_category": "cat_3_packaging"},
        {"entry_status": "filled", "net_return_pct": -0.07, "hold_days": 10, "exit_date": "2024-01-15", "sector_category": "cat_3_packaging"},
        {"entry_status": "filled", "net_return_pct": 0.05, "hold_days": 8, "exit_date": "2024-01-20", "sector_category": "cat_1_silicon_ip"},
        {"entry_status": "filled", "net_return_pct": 0.03, "hold_days": 6, "exit_date": "2024-01-22", "sector_category": "cat_1_silicon_ip"},
    ])
    gates = GateConfig(min_trades=10, min_win_rate=0.45, min_profit_factor=1.05, max_drawdown_pct=-0.20)
    cats = ["cat_3_packaging", "cat_1_silicon_ip"]

    sm = compute_split_metrics(trades, gates, cats)
    assert sm.n_trades == 4
    assert "cat_3_packaging" in sm.cat_metrics
    assert sm.cat_metrics["cat_3_packaging"].n_trades == 2
    assert sm.cat_metrics["cat_1_silicon_ip"].n_trades == 2
    assert sm.cat_metrics["cat_1_silicon_ip"].win_rate == 1.0


# ───────────────────────────────────────────────────────────────────────────
# 10. Output persistence
# ───────────────────────────────────────────────────────────────────────────

def test_write_best_params_produces_valid_yaml(tmp_path: Path):
    params = {
        "price_position.min_return_60d": -0.10,
        "ema.pre_breakout_ema_spread_max": 0.04,
        "classification.pre_breakout_score_min": 60,
    }
    out_path = tmp_path / "best_params.yaml"
    write_best_params(out_path, params)
    assert out_path.exists()

    import yaml
    with out_path.open("r", encoding="utf-8") as f:
        loaded = yaml.safe_load(f)
    assert "surge_candidate" in loaded
    assert loaded["surge_candidate"]["price_position"]["min_return_60d"] == -0.10
    assert loaded["surge_candidate"]["ema"]["pre_breakout_ema_spread_max"] == 0.04
    assert loaded["surge_candidate"]["classification"]["pre_breakout_score_min"] == 60


def test_write_runs_csv_and_summary(tmp_path: Path):
    train = SplitMetrics(n_trades=30, win_rate=0.60, avg_return_pct=0.02, profit_factor=1.5, max_drawdown=-0.10, expectancy=0.012, gates_passed=3)
    cat3_val = CategoryMetrics(category="cat_3_packaging", n_trades=10, win_rate=0.70, avg_return_pct=0.03, profit_factor=2.0, max_drawdown=-0.08, expectancy=0.020, gates_passed=4)
    val = SplitMetrics(n_trades=15, win_rate=0.65, avg_return_pct=0.025, profit_factor=1.7, max_drawdown=-0.09, expectancy=0.016, gates_passed=3)
    val.cat_metrics["cat_3_packaging"] = cat3_val

    r1 = TrialResult(trial_id=1, params_hash="abc123", params={"a": 1}, train=train, validation=val, objective_score=350.5, overfit_warning=False, success=True)

    runs_csv = tmp_path / "runs.csv"
    write_runs_csv(runs_csv, [r1])
    assert runs_csv.exists()

    df = pd.read_csv(runs_csv, encoding="utf-8-sig")
    assert df.iloc[0]["trial_id"] == 1
    assert df.iloc[0]["val_cat3_gates"] == 4

    summary = tmp_path / "summary.json"
    config = OptimizerConfig(target="cat3")
    write_best_summary(summary, r1, config, trials_run=1, recommendation="可進一步人工檢查")
    assert summary.exists()
    import json
    with summary.open("r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["recommendation"] == "可進一步人工檢查"
    assert "objective_formula" in data

    validation_csv = tmp_path / "validation.csv"
    write_validation_report(validation_csv, [r1])
    assert validation_csv.exists()


def test_derive_recommendation_paths():
    train = SplitMetrics(n_trades=30, win_rate=0.6, avg_return_pct=0.02, profit_factor=1.5, max_drawdown=-0.10, gates_passed=3)
    val_pass = SplitMetrics(n_trades=35, win_rate=0.6, avg_return_pct=0.025, profit_factor=1.7, max_drawdown=-0.10, gates_passed=4)

    r_passing = TrialResult(trial_id=1, params_hash="x", params={}, train=train, validation=val_pass, objective_score=400, overfit_warning=False, success=True)
    assert derive_recommendation(r_passing, "cat3") == "可進一步人工檢查"

    r_overfit = TrialResult(trial_id=1, params_hash="x", params={}, train=train, validation=val_pass, objective_score=400, overfit_warning=True, success=True)
    assert derive_recommendation(r_overfit, "cat3") == "可能過度擬合"

    val_low = SplitMetrics(n_trades=8, win_rate=0.7, avg_return_pct=0.03, profit_factor=2.0, max_drawdown=-0.08, gates_passed=4)
    r_low = TrialResult(trial_id=1, params_hash="x", params={}, train=train, validation=val_low, objective_score=400, overfit_warning=False, success=True)
    assert derive_recommendation(r_low, "cat3") == "需要更多資料"

    val_fail = SplitMetrics(n_trades=5, win_rate=0.3, avg_return_pct=-0.01, profit_factor=0.6, max_drawdown=-0.20, gates_passed=0)
    r_fail = TrialResult(trial_id=1, params_hash="x", params={}, train=train, validation=val_fail, objective_score=10, overfit_warning=False, success=False)
    assert derive_recommendation(r_fail, "cat3") == "不建議套用"


def test_load_search_space_from_default(tmp_path: Path):
    # Use the actual default search space file
    default_path = Path(__file__).resolve().parent.parent / "app" / "services" / "backtest" / "v1" / "optimizer_search_space.yaml"
    assert default_path.exists(), f"Default search space not found at {default_path}"
    space = load_search_space(default_path)
    assert len(space) > 0
    # Each value should be a list
    for k, v in space.items():
        assert isinstance(v, list), f"Search space value for {k} must be list, got {type(v)}"
        assert len(v) > 0


def test_default_search_space_respects_ema_transition_invariant():
    default_path = Path(__file__).resolve().parent.parent / "app" / "services" / "backtest" / "v1" / "optimizer_search_space.yaml"
    space = load_search_space(default_path)

    vals = space["classification.pre_breakout_ema_transition_score_min"]

    assert min(vals) >= 30


def test_objective_formula_string_exists():
    """Ensure OBJECTIVE_FORMULA is non-empty (it's written to best_summary.json)."""
    assert OBJECTIVE_FORMULA
    assert "val_gates_passed" in OBJECTIVE_FORMULA


# ───────────────────────────────────────────────────────────────────────────
# AI-loop feature tests (iteration + dim_analysis + summary_for_llm)
# ───────────────────────────────────────────────────────────────────────────

def _make_trial(trial_id: int, score_min: int, obj: float, val_wr: float) -> TrialResult:
    train = SplitMetrics(n_trades=20, win_rate=val_wr + 0.05, avg_return_pct=0.02, profit_factor=1.5, max_drawdown=-0.10, gates_passed=2)
    val = SplitMetrics(n_trades=15, win_rate=val_wr, avg_return_pct=0.018, profit_factor=1.4, max_drawdown=-0.10, gates_passed=2)
    val.cat_metrics["cat_3_packaging"] = CategoryMetrics(
        category="cat_3_packaging", n_trades=10, win_rate=val_wr + 0.10,
        avg_return_pct=0.025, profit_factor=1.6, max_drawdown=-0.08, expectancy=0.015,
        gates_passed=3,
    )
    return TrialResult(
        trial_id=trial_id, params_hash=f"h{trial_id}",
        params={"classification.pre_breakout_score_min": score_min, "ema.spread": 0.04},
        train=train, validation=val, objective_score=obj,
        overfit_warning=False, success=False,
    )


def _make_adaptive_trial(trial_id: int, params: dict, obj: float, val_n: int = 10) -> TrialResult:
    train = SplitMetrics(n_trades=max(10, val_n), win_rate=0.55, avg_return_pct=0.01, profit_factor=1.3, max_drawdown=-0.10, gates_passed=2)
    val = SplitMetrics(n_trades=val_n, win_rate=0.55, avg_return_pct=0.01, profit_factor=1.3, max_drawdown=-0.10, gates_passed=2)
    return TrialResult(
        trial_id=trial_id,
        params_hash=f"a{trial_id}",
        params=params,
        train=train,
        validation=val,
        objective_score=obj,
        overfit_warning=False,
        success=False,
    )


def _make_adaptive_trial_with_overfit(
    trial_id: int,
    params: dict,
    obj: float,
    *,
    overfit: bool,
    val_n: int = 10,
) -> TrialResult:
    trial = _make_adaptive_trial(trial_id, params, obj, val_n=val_n)
    trial.overfit_warning = overfit
    return trial


# ───────────────────────────────────────────────────────────────────────────
# Adaptive sampler tests
# ───────────────────────────────────────────────────────────────────────────

def test_weighted_sampling_prefers_high_weight_value():
    space = {"a": ["cold", "hot"], "b": [1]}
    weights = {"a": {"cold": 1.0, "hot": 100.0}, "b": {1: 1.0}}
    rng = random.Random(123)

    samples = [
        sample_params_weighted(space, rng, weights, exploration_prob=0.0)["a"]
        for _ in range(300)
    ]

    assert samples.count("hot") > 285


def test_weighted_sampling_keeps_uniform_exploration_path():
    space = {"a": ["left", "right"]}
    weights = {"a": {"left": 999.0, "right": 1.0}}
    rng = random.Random(456)

    samples = [
        sample_params_weighted(space, rng, weights, exploration_prob=1.0)["a"]
        for _ in range(100)
    ]

    assert set(samples) == {"left", "right"}


def test_unique_param_sampler_avoids_duplicates():
    space = {"a": [1, 2], "b": ["x", "y"]}
    rng = random.Random(0)
    samples = sample_unique_params(space, rng, 4)
    hashes = [params_hash(s) for s in samples]

    assert len(samples) == 4
    assert len(set(hashes)) == 4


def test_unique_param_sampler_stops_when_grid_exhausted():
    space = {"a": [1], "b": ["x", "y"]}
    rng = random.Random(0)
    samples = sample_unique_params(space, rng, 10)

    assert len(samples) == 2
    assert len({params_hash(s) for s in samples}) == 2


def test_unique_param_sampler_respects_seen_hashes():
    space = {"a": [1, 2], "b": ["x"]}
    already_seen = {params_hash({"a": 1, "b": "x"})}
    rng = random.Random(0)

    samples = sample_unique_params(space, rng, 2, seen_hashes=already_seen)

    assert samples == [{"a": 2, "b": "x"}]
    assert len(already_seen) == 2


def test_adaptive_weights_boost_elite_values():
    space = {"score": [50, 55, 60], "stop": [0.07, 0.10]}
    results = [
        _make_adaptive_trial(1, {"score": 50, "stop": 0.07}, obj=10),
        _make_adaptive_trial(2, {"score": 60, "stop": 0.10}, obj=300),
        _make_adaptive_trial(3, {"score": 60, "stop": 0.07}, obj=250),
    ]

    weights = build_adaptive_value_weights(results, space, min_elites=2)

    assert weights["score"][60] > weights["score"][50]
    assert weights["stop"][0.10] > 1.0


def test_adaptive_weights_ignore_rejected_trials_when_valid_exists():
    space = {"score": [50, 60]}
    results = [
        _make_adaptive_trial(1, {"score": 50}, obj=9999, val_n=1),
        _make_adaptive_trial(2, {"score": 60}, obj=100, val_n=10),
        _make_adaptive_trial(3, {"score": 60}, obj=90, val_n=9),
    ]

    weights = build_adaptive_value_weights(results, space, min_elites=2)

    assert weights["score"][60] > weights["score"][50]


def test_adaptive_weights_prefer_non_overfit_trials_when_available():
    space = {"score": [50, 60]}
    results = [
        _make_adaptive_trial_with_overfit(1, {"score": 50}, obj=500, overfit=True),
        _make_adaptive_trial_with_overfit(2, {"score": 60}, obj=100, overfit=False),
        _make_adaptive_trial_with_overfit(3, {"score": 60}, obj=90, overfit=False),
    ]

    weights = build_adaptive_value_weights(results, space, min_elites=2)

    assert weights["score"][60] > weights["score"][50]


def test_adaptive_weights_fall_back_to_overfit_when_no_stable_trials():
    space = {"score": [50, 60]}
    results = [
        _make_adaptive_trial_with_overfit(1, {"score": 50}, obj=500, overfit=True),
        _make_adaptive_trial_with_overfit(2, {"score": 60}, obj=100, overfit=True),
    ]

    weights = build_adaptive_value_weights(results, space, min_elites=2)

    assert weights["score"][50] > 1.0
    assert weights["score"][60] > 1.0


def test_adaptive_weights_fall_back_when_all_trials_rejected():
    space = {"score": [50, 60]}
    results = [
        _make_adaptive_trial(1, {"score": 50}, obj=20, val_n=1),
        _make_adaptive_trial(2, {"score": 60}, obj=10, val_n=1),
    ]

    weights = build_adaptive_value_weights(results, space, min_elites=2)

    assert weights["score"][50] > 1.0
    assert weights["score"][60] > 1.0


def test_adaptive_batch_size_scales_with_workers():
    assert _adaptive_batch_size(3, 4) == 3
    assert _adaptive_batch_size(80, 1) == 8
    assert _adaptive_batch_size(80, 4) == 12


def test_dimension_analysis_identifies_dominant_value():
    """dim_analysis 應該揭示哪個 score_min 平均 objective 最高。"""
    search_space = {
        "classification.pre_breakout_score_min": [55, 60, 65],
        "ema.spread": [0.03, 0.04, 0.05],
    }
    results = [
        _make_trial(1, 55, 100.0, 0.40),
        _make_trial(2, 55, 120.0, 0.45),
        _make_trial(3, 60, 300.0, 0.60),  # ← 60 dominates
        _make_trial(4, 60, 280.0, 0.62),
        _make_trial(5, 65, 150.0, 0.42),
        _make_trial(6, 65, 130.0, 0.41),
    ]
    analysis = compute_dimension_analysis(results, search_space)
    assert "classification.pre_breakout_score_min" in analysis
    by_val = analysis["classification.pre_breakout_score_min"]
    assert by_val["60"]["avg_obj"] > by_val["55"]["avg_obj"]
    assert by_val["60"]["avg_obj"] > by_val["65"]["avg_obj"]
    assert by_val["60"]["n_trials"] == 2


def test_convergence_summary_tracks_running_best():
    results = [
        _make_trial(1, 55, 100.0, 0.4),
        _make_trial(2, 60, 250.0, 0.5),   # new best
        _make_trial(3, 60, 200.0, 0.5),
        _make_trial(4, 65, 320.0, 0.6),   # new best
        _make_trial(5, 60, 180.0, 0.5),
    ]
    summary = compute_convergence_summary(results)
    assert summary["best_so_far_curve"] == [100.0, 250.0, 250.0, 320.0, 320.0]
    assert summary["total_trials"] == 5


def test_summary_for_llm_contains_all_ai_fields(tmp_path: Path):
    search_space = {
        "classification.pre_breakout_score_min": [55, 60, 65],
    }
    results = [
        _make_trial(1, 55, 100.0, 0.45),
        _make_trial(2, 60, 350.0, 0.65),
        _make_trial(3, 65, 200.0, 0.50),
    ]
    best = results[1]  # trial 2 has highest obj
    config = OptimizerConfig(target="cat3", max_trials=3)

    out_path = tmp_path / "summary_for_llm.json"
    write_summary_for_llm(
        out_path,
        results=results,
        best=best,
        config=config,
        search_space=search_space,
        iteration=1,
        recommendation="可進一步人工檢查",
    )
    assert out_path.exists()

    import json
    with out_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    # Required AI-readable fields
    assert data["iteration"] == 1
    assert data["target"] == "cat3"
    assert data["trials_run"] == 3
    assert data["recommendation"] == "可進一步人工檢查"
    assert "best_trial" in data
    assert "top_5_trials" in data
    assert "dim_analysis" in data
    assert "convergence" in data
    assert "current_search_space" in data
    assert "gates_used" in data
    assert "ai_instructions" in data

    # Best trial info
    assert data["best_trial"]["trial_id"] == 2
    assert data["best_objective"] == 350.0

    # Top 5 (we have 3 trials)
    assert len(data["top_5_trials"]) == 3
    assert data["top_5_trials"][0]["trial_id"] == 2  # sorted desc

    # Dim analysis is keyed by dotted path
    assert "classification.pre_breakout_score_min" in data["dim_analysis"]
