"""Parameter optimizer engine for the 起漲前觀察 strategy.

LLM is NOT involved per-trial. The flow is:
1. Sample params from search space
2. Build override dict, write temp YAML, set env var, clear lru_cache
3. Run signal_replay + trade_simulator on train_dates and val_dates separately
4. Compute per-category and overall metrics for each split
5. Score by composite objective; check gates; flag overfit
6. Persist trial row to CSV; track best by objective
7. Stop early if target gates fully passed; else continue to max_trials

The composite objective formula (visible in best_summary.json):
    score = val_gates * 100
          + val.win_rate * 30
          + val.avg_return_pct * 500
          + min(val.profit_factor, 5.0) * 8
          + val.expectancy * 200
          - abs(train.win_rate - val.win_rate) * 50
          - abs(train.avg_return_pct - val.avg_return_pct) * 200
          - low_sample_penalty
          - excess_drawdown_penalty
          + target_bonus  (cat3 specific gates × 50, or mean all-cat × 50)
"""
from __future__ import annotations

import csv
import hashlib
import json
import logging
import os
import random
import tempfile
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional

import pandas as pd
import yaml

from backend.app.services.backtest.historical_data_store import (
    CachedHistoricalDataStore,
    HistoricalDataStore,
)
from backend.app.services.backtest.metrics import compute_metrics
from backend.app.services.backtest.optimizer_config import (
    CategoryMetrics,
    GateConfig,
    OptimizerConfig,
    SplitMetrics,
    TrialResult,
    detect_overfit,
    gates_passed_count,
)
from backend.app.services.backtest.signal_replay import (
    ReplayConfig,
    load_signals,
    replay_signals,
)
from backend.app.services.backtest.trade_simulator import (
    TradeRules,
    load_trades,
    simulate_trades,
)
from backend.app.services.screener_rules import load_surge_candidate_rules
from backend.app.services.sector_service import (
    list_ai_tech_codes,
    list_codes_by_category,
)

logger = logging.getLogger(__name__)


# ───────────────────────────────────────────────────────────────────────────
# Search space sampling
# ───────────────────────────────────────────────────────────────────────────

def load_search_space(path: Path | str) -> dict[str, list]:
    with Path(path).open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    space = data.get("search_space", {})
    if not isinstance(space, dict) or not space:
        raise ValueError(f"Invalid or empty search_space in {path}")
    return space


def sample_params_random(search_space: dict[str, list], rng: random.Random) -> dict[str, Any]:
    """Pick one value from each dimension. Returns {dotted_key: value}."""
    return {k: rng.choice(values) for k, values in search_space.items()}


def grid_iterator(search_space: dict[str, list]) -> Iterable[dict[str, Any]]:
    """Cartesian product. Yields {dotted_key: value} dicts. Caller responsible for size check."""
    keys = list(search_space.keys())
    from itertools import product
    for combo in product(*[search_space[k] for k in keys]):
        yield dict(zip(keys, combo))


def estimate_grid_size(search_space: dict[str, list]) -> int:
    n = 1
    for v in search_space.values():
        n *= len(v)
    return n


def params_hash(params: dict[str, Any]) -> str:
    """Stable deterministic hash of a params dict."""
    blob = json.dumps(params, sort_keys=True, default=str)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]


# ───────────────────────────────────────────────────────────────────────────
# Override file plumbing
# ───────────────────────────────────────────────────────────────────────────

def expand_dotted(params: dict[str, Any]) -> dict[str, Any]:
    """{'a.b.c': 1} → {'a': {'b': {'c': 1}}}"""
    out: dict[str, Any] = {}
    for key, value in params.items():
        cursor = out
        parts = key.split(".")
        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[parts[-1]] = value
    return out


def deep_merge(base: dict, override: dict) -> dict:
    """Recursive dict merge — override wins; doesn't mutate inputs."""
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def write_override_yaml(merged_rules: dict, temp_dir: Path) -> Path:
    """Write merged rules to a temp YAML file in the form {surge_candidate: {...}}."""
    temp_dir.mkdir(parents=True, exist_ok=True)
    path = temp_dir / f"override_{int(time.time()*1000)}_{os.getpid()}.yaml"
    payload = {"surge_candidate": merged_rules}
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(payload, f, sort_keys=False, allow_unicode=True)
    return path


def apply_override(override_path: Path) -> None:
    """Point load_surge_candidate_rules at override_path."""
    os.environ["RULES_V1_YAML_PATH"] = str(override_path)
    load_surge_candidate_rules.cache_clear()


def clear_override() -> None:
    os.environ.pop("RULES_V1_YAML_PATH", None)
    load_surge_candidate_rules.cache_clear()


# ───────────────────────────────────────────────────────────────────────────
# Split metrics computation
# ───────────────────────────────────────────────────────────────────────────

def compute_split_metrics(
    trades_df: pd.DataFrame,
    gates: GateConfig,
    categories: list[str],
) -> SplitMetrics:
    """Aggregate trades + per-category metrics + gate counts."""
    overall = compute_metrics(trades_df) if not trades_df.empty else None
    sm = SplitMetrics()

    if overall is None or overall.n_trades == 0:
        return sm

    sm.n_trades = overall.n_trades
    sm.win_rate = overall.win_rate
    sm.avg_return_pct = overall.avg_return
    sm.profit_factor = (
        overall.profit_factor
        if (overall.profit_factor is not None and overall.profit_factor != float("inf"))
        else 999.0
    )
    sm.max_drawdown = overall.max_drawdown
    sm.expectancy = overall.expectancy
    sm.gates_passed = gates_passed_count(sm, gates)

    # Per category
    filled = trades_df[trades_df.get("entry_status") == "filled"]
    for cat in categories:
        sub = filled[filled.get("sector_category") == cat]
        if sub.empty:
            sm.cat_metrics[cat] = CategoryMetrics(
                category=cat, n_trades=0, win_rate=0.0, avg_return_pct=0.0,
                profit_factor=0.0, max_drawdown=0.0, expectancy=0.0, gates_passed=0,
            )
            continue
        m = compute_metrics(sub)
        pf = m.profit_factor if (m.profit_factor is not None and m.profit_factor != float("inf")) else 999.0
        cat_m = CategoryMetrics(
            category=cat,
            n_trades=m.n_trades,
            win_rate=m.win_rate,
            avg_return_pct=m.avg_return,
            profit_factor=pf,
            max_drawdown=m.max_drawdown,
            expectancy=m.expectancy,
            gates_passed=0,
        )
        cat_m.gates_passed = gates_passed_count(cat_m, gates)
        sm.cat_metrics[cat] = cat_m

    return sm


# ───────────────────────────────────────────────────────────────────────────
# Objective scoring
# ───────────────────────────────────────────────────────────────────────────

OBJECTIVE_FORMULA = """\
score = val_gates_passed * 100
      + val.win_rate * 30
      + val.avg_return_pct * 500
      + min(val.profit_factor, 5.0) * 8
      + val.expectancy * 200
      - abs(train.win_rate - val.win_rate) * 50
      - abs(train.avg_return_pct - val.avg_return_pct) * 200
      - low_sample_penalty
      - excess_drawdown_penalty
      + target_bonus
"""


def compute_objective(
    train: SplitMetrics,
    val: SplitMetrics,
    config: OptimizerConfig,
) -> float:
    """Composite objective — higher is better. Formula in OBJECTIVE_FORMULA."""
    if val.n_trades == 0:
        # No validation trades → minimum score
        return -1000.0

    # HARD reject reward-hacked single-trade samples. n=1 with PF=999 is the
    # main failure mode we saw; n≥3 is statistically thin but not gaming.
    # Lowered from 5 → 3 in Phase 9.8 to accommodate small-universe runs
    # (e.g. cat3 only 7 stocks → val window naturally produces 2-5 trades).
    if val.n_trades < 3:
        return -2000.0

    g = config.gates
    score = 0.0

    # Gate count
    score += val.gates_passed * 100.0

    # Performance terms
    score += val.win_rate * 30.0
    score += val.avg_return_pct * 500.0
    pf = min(val.profit_factor, 5.0)
    score += pf * 8.0
    score += val.expectancy * 200.0

    # Overfit penalty
    if train.n_trades > 0:
        score -= abs(train.win_rate - val.win_rate) * 50.0
        score -= abs(train.avg_return_pct - val.avg_return_pct) * 200.0

    # Low sample penalty — quadratic so n=10 vs n=30 differs much more than the
    # old linear penalty. Coefficient bumped 5× so the optimizer values "more
    # trades" comparably to "another gate passed".
    if val.n_trades < g.min_trades:
        gap = g.min_trades - val.n_trades
        score -= (gap ** 1.5) * 5.0    # n=29 → -5, n=20 → -160, n=10 → -700, n=5 → -1400

    # Excess DD penalty (only if worse than threshold)
    if val.max_drawdown < g.max_drawdown_pct:
        score -= (g.max_drawdown_pct - val.max_drawdown) * 200.0

    # Target bonus
    if config.target == "cat3":
        cat3 = val.cat_metrics.get("cat_3_packaging")
        if cat3:
            score += cat3.gates_passed * 50.0
    elif config.target == "all":
        if val.cat_metrics:
            mean_g = sum(c.gates_passed for c in val.cat_metrics.values()) / len(val.cat_metrics)
            score += mean_g * 50.0

    return float(score)


def check_success(val: SplitMetrics, target: str, gates: GateConfig) -> bool:
    """Whether target gates are fully passed (4/4)."""
    if target == "cat3":
        cat3 = val.cat_metrics.get("cat_3_packaging")
        return bool(cat3 and cat3.gates_passed == 4)
    if target == "all":
        return bool(val.cat_metrics) and all(c.gates_passed == 4 for c in val.cat_metrics.values())
    return val.gates_passed == 4


# ───────────────────────────────────────────────────────────────────────────
# Trial execution
# ───────────────────────────────────────────────────────────────────────────

def split_dates(
    trading_dates: list[str], train_split: float
) -> tuple[list[str], list[str]]:
    """Chronological split. train_split must be in (0, 1)."""
    if not trading_dates:
        return [], []
    n = len(trading_dates)
    split_idx = int(n * train_split)
    return trading_dates[:split_idx], trading_dates[split_idx:]


def _run_segment(
    *,
    run_id: str,
    dates_segment: list[str],
    universe: list[str],
    candidate_types: list[str],
    data_store: HistoricalDataStore,
    db_path: Path,
    rules: TradeRules,
) -> pd.DataFrame:
    """Run replay + simulate for one date segment. Returns trades DataFrame."""
    if not dates_segment:
        return pd.DataFrame()

    cfg = ReplayConfig(
        run_id=run_id,
        start_date=dates_segment[0],
        end_date=dates_segment[-1],
        stock_universe=universe,
        target_candidate_types=candidate_types,
    )
    replay_signals(cfg, data_store=data_store, db_path=db_path)
    signals_df = load_signals(db_path, run_id)
    if signals_df.empty:
        return pd.DataFrame()
    simulate_trades(
        signals_df=signals_df,
        data_store=data_store,
        rules=rules,
        run_id=run_id,
        db_path=db_path,
    )
    return load_trades(db_path, run_id)


def _split_trade_rules_overrides(
    sampled_params: dict[str, Any],
    base_trade_rules: TradeRules,
) -> tuple[dict[str, Any], TradeRules]:
    """Phase 9.8: separate `trade_rules.*` keys from screener rules.

    Returns (screener_rule_params, effective_trade_rules).
    trade_rules.* keys are STRIPPED from screener params (so they don't pollute
    the rules YAML override) and applied to a fresh TradeRules instance.
    """
    rule_keys = {k: v for k, v in sampled_params.items() if not k.startswith("trade_rules.")}
    tr_overrides = {k[len("trade_rules."):]: v for k, v in sampled_params.items()
                    if k.startswith("trade_rules.")}
    # Build effective trade rules
    effective = TradeRules(
        max_hold_days=int(tr_overrides.get("max_hold_days", base_trade_rules.max_hold_days)),
        stop_loss_pct=float(tr_overrides.get("stop_loss_pct", base_trade_rules.stop_loss_pct)),
        target_pct=float(tr_overrides.get("target_pct", base_trade_rules.target_pct)),
        measured_move_method=str(tr_overrides.get("measured_move_method", base_trade_rules.measured_move_method)),
        measured_move_multiplier=float(tr_overrides.get("measured_move_multiplier", base_trade_rules.measured_move_multiplier)),
        commission_pct=base_trade_rules.commission_pct,
        transaction_tax_pct=base_trade_rules.transaction_tax_pct,
        slippage_pct=base_trade_rules.slippage_pct,
    )
    return rule_keys, effective


def run_trial(
    *,
    trial_id: int,
    sampled_params: dict[str, Any],
    config: OptimizerConfig,
    base_rules: dict,
    train_dates: list[str],
    val_dates: list[str],
    universe: list[str],
    data_store: HistoricalDataStore,
    db_path: Path,
    temp_dir: Path,
    trade_rules: TradeRules,
    categories: list[str],
) -> Optional[TrialResult]:
    """Execute one trial. Returns None if hard-error."""
    p_hash = params_hash(sampled_params)
    override_path = None

    # Phase 9.8: split trade_rules.* from screener rules; build effective trade_rules
    rule_params, trade_rules = _split_trade_rules_overrides(sampled_params, trade_rules)

    try:
        # Build merged rules (excluding trade_rules.* which aren't rules YAML keys)
        override_nested = expand_dotted(rule_params)
        merged = deep_merge(base_rules, override_nested)
        override_path = write_override_yaml(merged, temp_dir)

        # Apply override
        apply_override(override_path)

        # Run train segment
        train_run_id = f"opt_{trial_id:05d}_{p_hash}_train"
        train_trades = _run_segment(
            run_id=train_run_id,
            dates_segment=train_dates,
            universe=universe,
            candidate_types=config.candidate_types,
            data_store=data_store,
            db_path=db_path,
            rules=trade_rules,
        )

        # Run validation segment
        val_run_id = f"opt_{trial_id:05d}_{p_hash}_val"
        val_trades = _run_segment(
            run_id=val_run_id,
            dates_segment=val_dates,
            universe=universe,
            candidate_types=config.candidate_types,
            data_store=data_store,
            db_path=db_path,
            rules=trade_rules,
        )

        # Compute metrics
        train_m = compute_split_metrics(train_trades, config.gates, categories)
        val_m = compute_split_metrics(val_trades, config.gates, categories)

        # Objective + overfit + success
        objective = compute_objective(train_m, val_m, config)
        overfit, _reason = detect_overfit(train_m, val_m)
        success = check_success(val_m, config.target, config.gates)

        result = TrialResult(
            trial_id=trial_id,
            params_hash=p_hash,
            params=sampled_params,
            train=train_m,
            validation=val_m,
            objective_score=objective,
            overfit_warning=overfit,
            success=success,
        )
        return result

    except Exception as exc:
        logger.warning("trial %d crashed: %s", trial_id, exc)
        return None
    finally:
        # Cleanup
        clear_override()
        if override_path and override_path.exists():
            try:
                override_path.unlink()
            except OSError:
                pass


# ───────────────────────────────────────────────────────────────────────────
# Output persistence
# ───────────────────────────────────────────────────────────────────────────

def write_runs_csv(out_path: Path, results: list[TrialResult]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "trial_id", "params_hash", "objective_score",
        "train_n", "train_wr", "train_avg", "train_pf", "train_dd", "train_gates",
        "val_n", "val_wr", "val_avg", "val_pf", "val_dd", "val_gates",
        "val_cat3_n", "val_cat3_wr", "val_cat3_avg", "val_cat3_gates",
        "overfit_warning", "success",
    ]
    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            cat3 = r.validation.cat_metrics.get("cat_3_packaging")
            writer.writerow({
                "trial_id": r.trial_id,
                "params_hash": r.params_hash,
                "objective_score": round(r.objective_score, 4),
                "train_n": r.train.n_trades,
                "train_wr": round(r.train.win_rate, 4),
                "train_avg": round(r.train.avg_return_pct, 4),
                "train_pf": round(r.train.profit_factor, 4),
                "train_dd": round(r.train.max_drawdown, 4),
                "train_gates": r.train.gates_passed,
                "val_n": r.validation.n_trades,
                "val_wr": round(r.validation.win_rate, 4),
                "val_avg": round(r.validation.avg_return_pct, 4),
                "val_pf": round(r.validation.profit_factor, 4),
                "val_dd": round(r.validation.max_drawdown, 4),
                "val_gates": r.validation.gates_passed,
                "val_cat3_n": cat3.n_trades if cat3 else 0,
                "val_cat3_wr": round(cat3.win_rate, 4) if cat3 else 0,
                "val_cat3_avg": round(cat3.avg_return_pct, 4) if cat3 else 0,
                "val_cat3_gates": cat3.gates_passed if cat3 else 0,
                "overfit_warning": r.overfit_warning,
                "success": r.success,
            })


def write_best_params(out_path: Path, params: dict[str, Any]) -> None:
    """Write the best override in proper nested YAML form."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    nested = expand_dotted(params)
    payload = {"surge_candidate": nested}
    with out_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(payload, f, sort_keys=False, allow_unicode=True)


def write_best_summary(
    out_path: Path,
    best: TrialResult,
    config: OptimizerConfig,
    trials_run: int,
    recommendation: str,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now().isoformat(),
        "target": config.target,
        "method": config.method,
        "trials_run": trials_run,
        "best_trial_id": best.trial_id,
        "params_hash": best.params_hash,
        "best_objective": best.objective_score,
        "objective_formula": OBJECTIVE_FORMULA,
        "gates": config.gates.to_dict(),
        "params": best.params,
        "train_metrics": best.train.to_dict(),
        "validation_metrics": best.validation.to_dict(),
        "overfit_warning": best.overfit_warning,
        "success": best.success,
        "recommendation": recommendation,
    }
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, default=str)


def write_validation_report(out_path: Path, top_k_results: list[TrialResult]) -> None:
    """Top-K trials with category-level breakdown for human inspection."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for r in top_k_results:
        base = {
            "rank": 0,  # filled below
            "trial_id": r.trial_id,
            "objective": round(r.objective_score, 4),
            "val_gates": r.validation.gates_passed,
            "val_n": r.validation.n_trades,
            "val_wr": round(r.validation.win_rate, 4),
            "val_avg": round(r.validation.avg_return_pct, 4),
            "val_pf": round(r.validation.profit_factor, 4),
            "val_dd": round(r.validation.max_drawdown, 4),
            "overfit": r.overfit_warning,
            "success": r.success,
        }
        for cat_key, cat_m in r.validation.cat_metrics.items():
            base[f"{cat_key}_n"] = cat_m.n_trades
            base[f"{cat_key}_wr"] = round(cat_m.win_rate, 4)
            base[f"{cat_key}_gates"] = cat_m.gates_passed
        rows.append(base)

    if not rows:
        return
    # Sort by objective desc, then rank
    rows.sort(key=lambda r: r["objective"], reverse=True)
    for i, r in enumerate(rows, 1):
        r["rank"] = i

    # Union of all columns
    all_keys: list[str] = []
    for r in rows:
        for k in r.keys():
            if k not in all_keys:
                all_keys.append(k)

    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=all_keys)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def compute_dimension_analysis(
    results: list[TrialResult],
    search_space: dict[str, list],
) -> dict[str, dict[str, Any]]:
    """For each search dim, group trials by value and compute aggregate stats.

    Returns:
        {
            "classification.pre_breakout_score_min": {
                "55": {"n": 18, "avg_obj": 245.3, "max_obj": 380.5, "avg_val_wr": 0.52},
                "60": {"n": 16, "avg_obj": 320.5, "max_obj": 410.0, "avg_val_wr": 0.61},
                "65": {"n": 16, "avg_obj": 180.2, "max_obj": 220.1, "avg_val_wr": 0.43},
            },
            ...
        }

    AI can use this to identify which values for each dim correlate with better outcomes.
    """
    analysis: dict[str, dict[str, Any]] = {}
    for dim_key in search_space.keys():
        per_value: dict[str, list[TrialResult]] = {}
        for r in results:
            if dim_key not in r.params:
                continue
            v = r.params[dim_key]
            key_str = str(v)
            per_value.setdefault(key_str, []).append(r)

        dim_stats: dict[str, Any] = {}
        for v_str, trials in per_value.items():
            objs = [t.objective_score for t in trials]
            val_wrs = [t.validation.win_rate for t in trials if t.validation.n_trades > 0]
            val_n = [t.validation.n_trades for t in trials]
            cat3_gates = [
                t.validation.cat_metrics["cat_3_packaging"].gates_passed
                for t in trials
                if "cat_3_packaging" in t.validation.cat_metrics
            ]
            dim_stats[v_str] = {
                "n_trials": len(trials),
                "avg_obj": round(sum(objs) / len(objs), 2) if objs else 0.0,
                "max_obj": round(max(objs), 2) if objs else 0.0,
                "avg_val_wr": round(sum(val_wrs) / len(val_wrs), 4) if val_wrs else 0.0,
                "avg_val_n": round(sum(val_n) / len(val_n), 1) if val_n else 0.0,
                "avg_cat3_gates": round(sum(cat3_gates) / len(cat3_gates), 2) if cat3_gates else 0.0,
            }
        analysis[dim_key] = dim_stats
    return analysis


def compute_convergence_summary(results: list[TrialResult]) -> dict[str, Any]:
    """Track running best objective across trials to detect convergence/stagnation."""
    if not results:
        return {"best_so_far": [], "stalled_after_trial": None, "total_trials": 0}

    best_so_far: list[float] = []
    cur = -float("inf")
    for r in results:
        cur = max(cur, r.objective_score)
        best_so_far.append(round(cur, 2))

    last_improvement_trial = 0
    for i in range(1, len(best_so_far)):
        if best_so_far[i] > best_so_far[i - 1]:
            last_improvement_trial = i

    return {
        "best_so_far_curve": best_so_far,
        "stalled_after_trial": last_improvement_trial if (len(best_so_far) - last_improvement_trial > 20) else None,
        "stagnation_trials": len(best_so_far) - last_improvement_trial,
        "total_trials": len(results),
    }


def write_summary_for_llm(
    out_path: Path,
    *,
    results: list[TrialResult],
    best: TrialResult,
    config: OptimizerConfig,
    search_space: dict[str, list],
    iteration: int,
    recommendation: str,
) -> None:
    """Write a compact, AI-readable summary. Paste this file's content to your LLM
    for next-round search space adjustment.

    Format optimized for AI consumption — includes dim analysis showing which
    parameter values correlate with high objective scores.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Top 5 by objective
    top_5 = sorted(results, key=lambda r: r.objective_score, reverse=True)[:5]
    top_5_data = []
    for r in top_5:
        cat3 = r.validation.cat_metrics.get("cat_3_packaging")
        top_5_data.append({
            "trial_id": r.trial_id,
            "objective": round(r.objective_score, 2),
            "params": r.params,
            "val_n": r.validation.n_trades,
            "val_wr": round(r.validation.win_rate, 4),
            "val_avg_return": round(r.validation.avg_return_pct, 4),
            "val_pf": round(r.validation.profit_factor, 4),
            "val_dd": round(r.validation.max_drawdown, 4),
            "val_gates": r.validation.gates_passed,
            "cat3_n": cat3.n_trades if cat3 else 0,
            "cat3_wr": round(cat3.win_rate, 4) if cat3 else 0,
            "cat3_gates": cat3.gates_passed if cat3 else 0,
            "overfit": r.overfit_warning,
        })

    # Dim analysis — which values correlate with best outcomes
    dim_analysis = compute_dimension_analysis(results, search_space)

    # Convergence
    convergence = compute_convergence_summary(results)

    payload = {
        "iteration": iteration,
        "target": config.target,
        "trials_run": len(results),
        "success_criteria_met": best.success,
        "best_objective": round(best.objective_score, 2),
        "recommendation": recommendation,
        "best_trial": {
            "trial_id": best.trial_id,
            "params": best.params,
            "train": best.train.to_dict(),
            "validation": best.validation.to_dict(),
            "overfit_warning": best.overfit_warning,
        },
        "top_5_trials": top_5_data,
        "dim_analysis": dim_analysis,
        "convergence": convergence,
        "current_search_space": search_space,
        "gates_used": config.gates.to_dict(),
        "ai_instructions": (
            "Read dim_analysis to find which values yield highest avg_obj for each dim. "
            "Suggest a narrowed search_space for next iteration, focusing on top-performing values. "
            "Drop dims where avg_obj is flat across all values (no signal). "
            "If success_criteria_met=true, recommend stopping. "
            "If stalled_after_trial is set, consider expanding ranges or adding new dims."
        ),
    }

    with out_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, default=str)


def derive_recommendation(best: TrialResult, target: str) -> str:
    if not best.success:
        return "不建議套用"
    if best.overfit_warning:
        return "可能過度擬合"
    if best.validation.n_trades < 30:
        return "需要更多資料"
    return "可進一步人工檢查"


# ───────────────────────────────────────────────────────────────────────────
# Multiprocess worker (module-level so it's pickleable)
#
# Each worker pre-loads its own in-memory OHLCV cache via Pool initializer,
# then reuses it across all trials it's assigned. Stored in a process-global
# so we don't pickle a 30MB DataFrame dict per task.
# ───────────────────────────────────────────────────────────────────────────

_WORKER_CACHED_STORE: Optional[CachedHistoricalDataStore] = None


def _init_worker(db_path_str: str, universe: list[str], start_date: str, end_date: str) -> None:
    """Pool init — pre-load OHLCV cache once per worker process."""
    global _WORKER_CACHED_STORE
    _WORKER_CACHED_STORE = CachedHistoricalDataStore(
        db_path=Path(db_path_str),
        universe=universe,
        start_date=start_date,
        end_date=end_date,
    )


def _worker_run_trial(args: dict) -> Optional[TrialResult]:
    """Pool worker — each call runs one trial. Cache injected via process-global."""
    global _WORKER_CACHED_STORE
    if _WORKER_CACHED_STORE is None:
        # Defensive: should be set by initializer. Fall back to live SQLite.
        store = HistoricalDataStore(Path(args["db_path_str"]))
    else:
        store = _WORKER_CACHED_STORE
    return run_trial(
        trial_id=args["trial_id"],
        sampled_params=args["sampled_params"],
        config=args["config"],
        base_rules=args["base_rules"],
        train_dates=args["train_dates"],
        val_dates=args["val_dates"],
        universe=args["universe"],
        data_store=store,
        db_path=Path(args["db_path_str"]),
        temp_dir=Path(args["temp_dir_str"]),
        trade_rules=args["trade_rules"],
        categories=args["categories"],
    )


# ───────────────────────────────────────────────────────────────────────────
# Main orchestrator
# ───────────────────────────────────────────────────────────────────────────

def _resolve_universe(config: OptimizerConfig) -> list[str]:
    """Pick universe with precedence: explicit > category filter > full AI tech."""
    if config.universe:
        return list(config.universe)
    if config.universe_categories:
        codes: set[str] = set()
        for cat_key in config.universe_categories:
            codes |= list_codes_by_category(cat_key)
        return sorted(codes)
    return sorted(list_ai_tech_codes())


def run_optimization(
    config: OptimizerConfig,
    search_space: dict[str, list],
    *,
    progress_callback=None,
) -> tuple[list[TrialResult], Optional[TrialResult]]:
    """Run the full optimization loop. Returns (all_results, best_result)."""
    base_rules = load_surge_candidate_rules()  # snapshot of current rules
    rng = random.Random(config.seed)

    universe = _resolve_universe(config)
    if not universe:
        raise RuntimeError("Empty universe — no stocks to backtest.")

    # Trading dates — build the in-memory cache once per session. Drop-in
    # replacement for HistoricalDataStore; ~30× faster for backtest workloads.
    db_path = Path(config.db_path)
    data_store = CachedHistoricalDataStore(
        db_path=db_path,
        universe=universe,
        start_date=config.start_date,
        end_date=config.end_date,
    )
    logger.info("OHLCV cache loaded: %d stocks, %d total rows",
                len(data_store.list_stocks()), data_store.row_count())
    trading_dates = data_store.get_all_trading_dates(config.start_date, config.end_date)
    if len(trading_dates) < 100:
        raise RuntimeError(f"Insufficient trading dates: {len(trading_dates)} in [{config.start_date},{config.end_date}]")

    train_dates, val_dates = split_dates(trading_dates, config.train_split)
    logger.info(
        "Optimization range: %d trading dates total | train=%d (%s~%s) val=%d (%s~%s)",
        len(trading_dates),
        len(train_dates), train_dates[0] if train_dates else "—", train_dates[-1] if train_dates else "—",
        len(val_dates), val_dates[0] if val_dates else "—", val_dates[-1] if val_dates else "—",
    )

    # Temp directory for overrides
    temp_dir = Path(tempfile.gettempdir()) / "ai_stock_optimizer"
    temp_dir.mkdir(parents=True, exist_ok=True)

    # Base trade rules (Phase 9.8 aligned defaults — Flat Base O'Neil style).
    # Per-trial trade_rules.* params override this in run_trial.
    trade_rules = TradeRules(
        max_hold_days=0,           # unlimited (user thesis)
        stop_loss_pct=0.10,        # -10% (user thesis)
        target_pct=0.15,           # fallback when measured_move_method=="fixed"
        measured_move_method="box_range",
        measured_move_multiplier=0.85,
    )

    categories = ["cat_1_silicon_ip", "cat_2_foundry", "cat_3_packaging",
                  "cat_4_components", "cat_5_system_integration", "cat_6_cloud_software"]

    # Decide iteration strategy
    grid_size = estimate_grid_size(search_space)
    if config.method == "grid" and grid_size > 5000:
        logger.warning("Grid size %d > 5000, downgrading to random", grid_size)
        method = "random"
    else:
        method = config.method

    # Generate param sequence
    if method == "grid":
        iterable = list(grid_iterator(search_space))[:config.max_trials]
    else:
        iterable = [sample_params_random(search_space, rng) for _ in range(config.max_trials)]

    results: list[TrialResult] = []
    best: Optional[TrialResult] = None
    n_workers = max(1, int(config.n_workers))

    if n_workers == 1:
        # Sequential path — keep the original loop for determinism and easy debug.
        for trial_id, params in enumerate(iterable, start=1):
            result = run_trial(
                trial_id=trial_id,
                sampled_params=params,
                config=config,
                base_rules=base_rules,
                train_dates=train_dates,
                val_dates=val_dates,
                universe=universe,
                data_store=data_store,
                db_path=db_path,
                temp_dir=temp_dir,
                trade_rules=trade_rules,
                categories=categories,
            )
            if result is None:
                continue
            results.append(result)

            if best is None or result.objective_score > best.objective_score:
                best = result
                is_best = True
            else:
                is_best = False

            if progress_callback:
                progress_callback(result, best, is_best)

            if result.success:
                logger.info("trial %d hit success criteria — stopping early", trial_id)
                break

        return results, best

    # Parallel path — multiprocess Pool. Each worker opens its own DB connection,
    # owns its own env var override; SQLite serializes concurrent writes but each
    # trial uses unique run_id so rows don't conflict.
    from multiprocessing import Pool

    worker_args = [
        {
            "trial_id": trial_id,
            "sampled_params": params,
            "config": config,
            "base_rules": base_rules,
            "train_dates": train_dates,
            "val_dates": val_dates,
            "universe": universe,
            "db_path_str": str(db_path),
            "temp_dir_str": str(temp_dir),
            "trade_rules": trade_rules,
            "categories": categories,
        }
        for trial_id, params in enumerate(iterable, start=1)
    ]

    logger.info("running %d trials with %d parallel workers", len(worker_args), n_workers)

    with Pool(
        processes=n_workers,
        initializer=_init_worker,
        initargs=(str(db_path), universe, config.start_date, config.end_date),
    ) as pool:
        for result in pool.imap_unordered(_worker_run_trial, worker_args):
            if result is None:
                continue
            results.append(result)

            if best is None or result.objective_score > best.objective_score:
                best = result
                is_best = True
            else:
                is_best = False

            if progress_callback:
                progress_callback(result, best, is_best)

            if result.success:
                logger.info("trial %d hit success criteria — stopping submission", result.trial_id)
                # Terminate remaining workers; results already collected are kept.
                pool.terminate()
                break

    # Sort results by trial_id for deterministic downstream output.
    results.sort(key=lambda r: r.trial_id)
    return results, best
