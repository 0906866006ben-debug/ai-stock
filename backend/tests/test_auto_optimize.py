"""Tests for the Claude-driven closed-loop optimizer.

These tests must NEVER call the real Anthropic API. They cover:
  1. Missing API key raises a clear error
  2. Dry-run never instantiates a real Anthropic client
  3. Validator parses well-formed JSON
  4. Validator flags malformed JSON for repair
  5. Out-of-bounds values are dropped, not crashed
  6. Non-whitelisted keys are dropped
  7. Positive risk_score weight is rejected (invariant)
  8. Empty list under a key is dropped
  9. Lists longer than 7 are truncated
 10. Failed backtest enters repair flow with FakeAdvisor
 11. Repair attempts limit terminates the loop
 12. Regression detection (helper)
 13. next_search_space.yaml written per iter
 14. claude_request.json does not contain API key
 15. Logs/artifacts contain no API key string
 16. Production rules_v1.yaml is not modified
 17. stop_on_success terminates loop
 18. Stagnation stops after N iters
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import yaml

from backend.app.services.backtest import optimization_loop as loop_mod
from backend.app.services.backtest.llm_search_space_advisor import (
    AdvisorCallResult,
    AdvisorConfigError,
    FakeAdvisor,
    build_advisor,
)
from backend.app.services.backtest.optimization_loop import (
    LoopConfig,
    _apply_patch_to_search_space,
    _detect_regression,
    run_closed_loop,
)
from backend.app.services.backtest.optimizer_config import (
    CategoryMetrics,
    GateConfig,
    SplitMetrics,
    TrialResult,
)
from backend.app.services.backtest.search_space_validator import (
    ClaudeResponse,
    load_bounds_config,
    parse_response,
    to_rules_dotted_paths,
    validate,
    weight_patch_to_overrides,
)


BOUNDS_CONFIG_PATH = Path("backend/app/services/backtest/allowed_bounds.yaml")
SEARCH_SPACE_PATH = Path("backend/app/services/backtest/optimizer_search_space.yaml")
PRODUCTION_RULES_PATH = Path("backend/app/services/rules_v1.yaml")


@pytest.fixture(scope="module")
def bounds_config():
    return load_bounds_config(BOUNDS_CONFIG_PATH)


@pytest.fixture
def initial_search_space():
    with SEARCH_SPACE_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f).get("search_space", {})


# ───────────────────────────────────────────────────────────────────────
# Helpers — build a fake TrialResult / iter artifacts
# ───────────────────────────────────────────────────────────────────────

def _make_trial(*, trial_id: int = 1, obj: float = 100.0, gates: int = 4,
                cat3_gates: int = 4, n: int = 50, success: bool = True,
                overfit: bool = False) -> TrialResult:
    split = SplitMetrics(
        n_trades=n, win_rate=0.55, avg_return_pct=0.05,
        profit_factor=1.5, max_drawdown=-0.08, expectancy=0.02,
        gates_passed=gates,
        cat_metrics={
            "cat_3_packaging": CategoryMetrics(
                category="cat_3_packaging",
                n_trades=n, win_rate=0.6, avg_return_pct=0.06,
                profit_factor=1.6, max_drawdown=-0.07, expectancy=0.025,
                gates_passed=cat3_gates,
            )
        },
    )
    return TrialResult(
        trial_id=trial_id,
        params_hash=f"hash{trial_id}",
        params={"price_position.min_return_60d": -0.1},
        train=split, validation=split,
        objective_score=obj,
        success=success, overfit_warning=overfit,
    )


def _fake_run_optimization_factory(trials_pattern: list[TrialResult]):
    """Return a fake `run_optimization` that yields one trial per call."""
    counter = {"i": 0}

    def _fake(opt_config, search_space, progress_callback=None):
        i = counter["i"]
        counter["i"] += 1
        if i >= len(trials_pattern):
            i = len(trials_pattern) - 1
        trial = trials_pattern[i]
        return [trial], trial

    return _fake


def _patch_optimizer_writes(monkeypatch):
    """No-op all CSV/YAML/JSON writers so tests don't touch real artifacts dir."""
    for fn in (
        "write_runs_csv", "write_best_params", "write_best_summary",
        "write_validation_report", "write_summary_for_llm",
        "derive_recommendation",
    ):
        if fn == "derive_recommendation":
            monkeypatch.setattr(loop_mod, fn, lambda *a, **kw: "ok")
        else:
            monkeypatch.setattr(loop_mod, fn, lambda *a, **kw: None)


# ───────────────────────────────────────────────────────────────────────
# 1. Missing API key raises a clear error
# ───────────────────────────────────────────────────────────────────────

def test_missing_api_key_raises_clear_error(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(AdvisorConfigError) as excinfo:
        build_advisor(dry_run=False, model="claude-sonnet-4-6", temperature=0.2)
    assert "ANTHROPIC_API_KEY" in str(excinfo.value)


# ───────────────────────────────────────────────────────────────────────
# 2. Dry-run never instantiates the real Anthropic client
# ───────────────────────────────────────────────────────────────────────

def test_dry_run_uses_fake_advisor(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    advisor = build_advisor(dry_run=True, model="claude-sonnet-4-6", temperature=0.2)
    assert isinstance(advisor, FakeAdvisor)
    result = advisor.advise({"iteration": 1, "current_search_space": {"a": [1]}})
    parsed = json.loads(result.raw_text)
    assert parsed["action"] in {"update_search_space", "stop"}
    assert parsed["stop"] in {True, False}


# ───────────────────────────────────────────────────────────────────────
# 3. Validator parses well-formed JSON
# ───────────────────────────────────────────────────────────────────────

def test_validator_accepts_well_formed_json(bounds_config):
    payload = {
        "action": "update_search_space",
        "confidence": 0.8,
        "next_search_space": {
            "min_return_60d": [-0.10, -0.05],
            "pre_breakout_range_90d_min": [0.08, 0.10],
        },
        "weight_patch": {"base_compression_score": 0.20},
        "stop": False,
        "short_reason_codes": ["TIGHTEN_RANGE"],
    }
    result = validate(json.dumps(payload), bounds_config)
    assert result.valid is True
    assert result.cleaned is not None
    assert "min_return_60d" in result.cleaned.next_search_space
    assert result.cleaned.action == "update_search_space"


# ───────────────────────────────────────────────────────────────────────
# 4. Malformed JSON returns requires_repair=True
# ───────────────────────────────────────────────────────────────────────

def test_validator_flags_malformed_json_for_repair(bounds_config):
    bad = "this is not JSON, just prose from the model"
    result = validate(bad, bounds_config)
    assert result.valid is False
    assert result.requires_repair is True


# ───────────────────────────────────────────────────────────────────────
# 5. Out-of-bounds values dropped, not crashed
# ───────────────────────────────────────────────────────────────────────

def test_validator_drops_out_of_bounds_values(bounds_config):
    payload = {
        "action": "update_search_space",
        "confidence": 0.5,
        "next_search_space": {
            "min_return_60d": [-0.50, -0.20, 0.99],   # -0.50 and 0.99 OOB
        },
        "weight_patch": {},
        "stop": False,
        "short_reason_codes": [],
    }
    result = validate(json.dumps(payload), bounds_config)
    assert result.valid is True
    assert result.cleaned.next_search_space["min_return_60d"] == [-0.20]
    assert any("out-of-bounds" in w for w in result.warnings)


# ───────────────────────────────────────────────────────────────────────
# 6. Non-whitelisted keys dropped
# ───────────────────────────────────────────────────────────────────────

def test_validator_drops_non_whitelisted_keys(bounds_config):
    payload = {
        "action": "update_search_space",
        "confidence": 0.5,
        "next_search_space": {
            "min_return_60d": [-0.10],
            "evil_unknown_key": [42],
        },
        "weight_patch": {},
        "stop": False,
        "short_reason_codes": [],
    }
    result = validate(json.dumps(payload), bounds_config)
    assert result.valid is True
    assert "evil_unknown_key" in result.dropped_keys
    assert "evil_unknown_key" not in result.cleaned.next_search_space


# ───────────────────────────────────────────────────────────────────────
# 7. Positive risk_score weight rejected
# ───────────────────────────────────────────────────────────────────────

def test_validator_rejects_positive_risk_score(bounds_config):
    payload = {
        "action": "update_search_space",
        "confidence": 0.5,
        "next_search_space": {"min_return_60d": [-0.10]},
        "weight_patch": {"risk_score": 0.1},      # MUST be <= 0
        "stop": False,
        "short_reason_codes": [],
    }
    result = validate(json.dumps(payload), bounds_config)
    assert result.valid is True
    assert "risk_score" not in result.cleaned.weight_patch
    assert any("risk_score" in w for w in result.warnings)


# ───────────────────────────────────────────────────────────────────────
# 8. Empty list under a key is dropped
# ───────────────────────────────────────────────────────────────────────

def test_validator_drops_empty_lists(bounds_config):
    payload = {
        "action": "update_search_space",
        "confidence": 0.5,
        "next_search_space": {
            "min_return_60d": [],
            "pre_breakout_range_90d_min": [0.10],
        },
        "weight_patch": {},
        "stop": False,
        "short_reason_codes": [],
    }
    result = validate(json.dumps(payload), bounds_config)
    assert result.valid is True
    assert "min_return_60d" in result.dropped_keys
    assert "pre_breakout_range_90d_min" in result.cleaned.next_search_space


# ───────────────────────────────────────────────────────────────────────
# 9. Lists longer than 7 are truncated
# ───────────────────────────────────────────────────────────────────────

def test_validator_truncates_long_lists(bounds_config):
    payload = {
        "action": "update_search_space",
        "confidence": 0.5,
        "next_search_space": {
            "min_return_60d": [-0.25, -0.20, -0.15, -0.10, -0.08, -0.05, 0.0, 0.03, 0.05],
        },
        "weight_patch": {},
        "stop": False,
        "short_reason_codes": [],
    }
    result = validate(json.dumps(payload), bounds_config)
    assert result.valid is True
    assert len(result.cleaned.next_search_space["min_return_60d"]) <= 7


# ───────────────────────────────────────────────────────────────────────
# Loop-level tests with mocked run_optimization
# ───────────────────────────────────────────────────────────────────────

def _build_loop_config(tmp_path: Path, **overrides) -> LoopConfig:
    cfg_kwargs = dict(
        target="cat3",
        max_iterations=5,
        trials_per_iter=2,
        seed=42,
        stop_on_success=False,
        stagnation_iters=99,
        min_improvement=0.01,
        repair_attempts=2,
        rollback_on_regression=False,
        output_dir=str(tmp_path / "opt"),
        auto_dir=str(tmp_path / "auto"),
        bounds_config_path=str(BOUNDS_CONFIG_PATH),
    )
    cfg_kwargs.update(overrides)
    return LoopConfig(**cfg_kwargs)


# 10. Failed backtest enters repair flow
def test_repair_flow_triggers_on_backtest_failure(monkeypatch, tmp_path, initial_search_space):
    _patch_optimizer_writes(monkeypatch)

    # First call raises, then succeeds
    state = {"calls": 0}

    def flaky(opt_config, search_space, progress_callback=None):
        state["calls"] += 1
        if state["calls"] == 1:
            raise RuntimeError("simulated backtest failure")
        return [_make_trial()], _make_trial()

    monkeypatch.setattr(loop_mod, "run_optimization", flaky)

    loop_cfg = _build_loop_config(tmp_path, max_iterations=1)
    advisor = FakeAdvisor()
    global_best, history = run_closed_loop(
        loop_config=loop_cfg, advisor=advisor,
        initial_search_space=initial_search_space,
    )
    repair_log = tmp_path / "opt" / "iter_01" / "repair_log.json"
    assert repair_log.exists()
    assert global_best is not None  # second attempt succeeded


# 11. Repair attempts limit stops
def test_repair_attempts_limit(monkeypatch, tmp_path, initial_search_space):
    _patch_optimizer_writes(monkeypatch)

    def always_fail(opt_config, search_space, progress_callback=None):
        raise RuntimeError("always fails")

    monkeypatch.setattr(loop_mod, "run_optimization", always_fail)

    loop_cfg = _build_loop_config(tmp_path, max_iterations=3, repair_attempts=2)
    advisor = FakeAdvisor()
    global_best, history = run_closed_loop(
        loop_config=loop_cfg, advisor=advisor,
        initial_search_space=initial_search_space,
    )
    assert global_best is None  # never succeeded
    assert len(history) == 0


# 12. Regression detection helper
def test_detect_regression_helper():
    prev = {"best_obj": 200, "val_pf": 1.6, "val_dd": -0.08,
            "val_n": 80, "val_gates": 4}
    cur_regressed = {"best_obj": 100, "val_pf": 1.0, "val_dd": -0.18,
                     "val_n": 30, "val_gates": 2}
    cur_ok = {"best_obj": 210, "val_pf": 1.7, "val_dd": -0.07,
              "val_n": 90, "val_gates": 4}
    assert _detect_regression(prev, cur_regressed) is not None
    assert _detect_regression(prev, cur_ok) is None
    assert _detect_regression(None, cur_ok) is None


# 13. next_search_space.yaml written each iter
def test_next_search_space_yaml_written(monkeypatch, tmp_path, initial_search_space):
    _patch_optimizer_writes(monkeypatch)
    monkeypatch.setattr(loop_mod, "run_optimization",
                        _fake_run_optimization_factory([_make_trial(success=False)]))
    loop_cfg = _build_loop_config(tmp_path, max_iterations=2)
    advisor = FakeAdvisor()
    run_closed_loop(loop_config=loop_cfg, advisor=advisor,
                    initial_search_space=initial_search_space)
    nxt = tmp_path / "opt" / "iter_01" / "next_search_space.yaml"
    assert nxt.exists()
    loaded = yaml.safe_load(nxt.read_text(encoding="utf-8"))
    assert "search_space" in loaded


# 14. claude_request.json never contains api key
def test_claude_request_no_api_key(monkeypatch, tmp_path, initial_search_space):
    _patch_optimizer_writes(monkeypatch)
    monkeypatch.setattr(loop_mod, "run_optimization",
                        _fake_run_optimization_factory([_make_trial(success=False)]))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-DO-NOT-LEAK-12345")
    loop_cfg = _build_loop_config(tmp_path, max_iterations=2)
    advisor = FakeAdvisor()
    run_closed_loop(loop_config=loop_cfg, advisor=advisor,
                    initial_search_space=initial_search_space)
    req = tmp_path / "opt" / "iter_01" / "claude_request.json"
    assert req.exists()
    contents = req.read_text(encoding="utf-8")
    assert "sk-ant-test-DO-NOT-LEAK-12345" not in contents
    assert "api_key" not in contents.lower()


# 15. Artifacts directory contains no API key string anywhere
def test_artifacts_contain_no_api_key(monkeypatch, tmp_path, initial_search_space):
    _patch_optimizer_writes(monkeypatch)
    monkeypatch.setattr(loop_mod, "run_optimization",
                        _fake_run_optimization_factory([_make_trial(success=False)]))
    secret = "sk-ant-LEAK-SENTINEL-987654321"
    monkeypatch.setenv("ANTHROPIC_API_KEY", secret)
    loop_cfg = _build_loop_config(tmp_path, max_iterations=2)
    advisor = FakeAdvisor()
    run_closed_loop(loop_config=loop_cfg, advisor=advisor,
                    initial_search_space=initial_search_space)
    # Scan everything under tmp_path
    leak_paths = []
    for p in tmp_path.rglob("*"):
        if p.is_file():
            try:
                if secret in p.read_text(encoding="utf-8", errors="ignore"):
                    leak_paths.append(p)
            except Exception:
                pass
    assert leak_paths == []


# 16. Production rules_v1.yaml is not modified
def test_production_rules_not_modified(monkeypatch, tmp_path, initial_search_space):
    _patch_optimizer_writes(monkeypatch)
    monkeypatch.setattr(loop_mod, "run_optimization",
                        _fake_run_optimization_factory([_make_trial()]))
    before = PRODUCTION_RULES_PATH.read_bytes() if PRODUCTION_RULES_PATH.exists() else None
    loop_cfg = _build_loop_config(tmp_path, max_iterations=1)
    advisor = FakeAdvisor()
    run_closed_loop(loop_config=loop_cfg, advisor=advisor,
                    initial_search_space=initial_search_space)
    after = PRODUCTION_RULES_PATH.read_bytes() if PRODUCTION_RULES_PATH.exists() else None
    assert before == after


# 17. stop_on_success terminates loop
def test_stop_on_success(monkeypatch, tmp_path, initial_search_space):
    _patch_optimizer_writes(monkeypatch)
    success_trial = _make_trial(success=True, overfit=False, gates=4, cat3_gates=4)
    monkeypatch.setattr(loop_mod, "run_optimization",
                        _fake_run_optimization_factory([success_trial]))
    loop_cfg = _build_loop_config(tmp_path, max_iterations=10, stop_on_success=True)
    advisor = FakeAdvisor()
    global_best, history = run_closed_loop(
        loop_config=loop_cfg, advisor=advisor,
        initial_search_space=initial_search_space,
    )
    assert len(history) == 1  # stopped after first success
    assert global_best is not None


# 18. Stagnation stops after N iters
def test_stagnation_stops_loop(monkeypatch, tmp_path, initial_search_space):
    _patch_optimizer_writes(monkeypatch)
    # All trials have identical objective → no improvement
    flat_trial = _make_trial(obj=50.0, success=False, gates=2, cat3_gates=1)
    monkeypatch.setattr(loop_mod, "run_optimization",
                        _fake_run_optimization_factory([flat_trial]))
    loop_cfg = _build_loop_config(tmp_path, max_iterations=10, stagnation_iters=2,
                                  min_improvement=10.0, stop_on_success=False)
    advisor = FakeAdvisor()
    global_best, history = run_closed_loop(
        loop_config=loop_cfg, advisor=advisor,
        initial_search_space=initial_search_space,
    )
    # First iter sets baseline; +2 stagnant iters trigger stop → total <= 3
    assert len(history) <= 3


# ───────────────────────────────────────────────────────────────────────
# Bonus: helper translations between short keys ↔ dotted paths
# ───────────────────────────────────────────────────────────────────────

def test_to_rules_dotted_paths(bounds_config):
    mapping = bounds_config["parameter_mapping"]
    short = {"min_return_60d": [-0.1, -0.05], "max_ema_spread": [0.05]}
    dotted = to_rules_dotted_paths(short, mapping)
    assert "price_position.min_return_60d" in dotted
    assert "ema.pre_breakout_ema_spread_max" in dotted


def test_weight_patch_to_overrides():
    out = weight_patch_to_overrides({"base_compression_score": 0.2,
                                     "risk_score": -0.1})
    assert out == {
        "scoring.pre_breakout_weights.base_compression_score": [0.2],
        "scoring.pre_breakout_weights.risk_score": [-0.1],
    }
