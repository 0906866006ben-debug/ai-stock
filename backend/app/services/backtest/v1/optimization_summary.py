"""Compact summary builder for Claude API consumption.

Reads `iter_NN/` artifacts from optimization.py and assembles a payload optimized
for token efficiency (~3-5 KB JSON). Keeps only what Claude needs to advise on
the next search space.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import pandas as pd


def _load_json(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _failed_gates_summary(top_trials: list[dict], gate_config: dict) -> dict:
    """Aggregate which gates fail most often + average gap from threshold."""
    if not top_trials or not gate_config:
        return {}

    fail_count = {"min_trades": 0, "min_win_rate": 0, "min_profit_factor": 0, "max_drawdown": 0}
    gap_sum = {"min_trades": 0.0, "min_win_rate": 0.0, "min_profit_factor": 0.0, "max_drawdown": 0.0}

    for t in top_trials:
        n = t.get("val_n", 0)
        wr = t.get("val_wr", 0.0)
        pf = t.get("val_pf", 0.0)
        dd = t.get("val_dd", 0.0)

        if n < gate_config["min_trades"]:
            fail_count["min_trades"] += 1
            gap_sum["min_trades"] += gate_config["min_trades"] - n
        if wr < gate_config["min_win_rate"]:
            fail_count["min_win_rate"] += 1
            gap_sum["min_win_rate"] += gate_config["min_win_rate"] - wr
        if pf < gate_config["min_profit_factor"]:
            fail_count["min_profit_factor"] += 1
            gap_sum["min_profit_factor"] += gate_config["min_profit_factor"] - pf
        if dd < gate_config["max_drawdown_pct"]:
            fail_count["max_drawdown"] += 1
            gap_sum["max_drawdown"] += gate_config["max_drawdown_pct"] - dd

    n_total = max(1, len(top_trials))
    summary = {}
    for k in fail_count:
        if fail_count[k] > 0:
            summary[k] = {
                "fail_count": fail_count[k],
                "fail_rate": round(fail_count[k] / n_total, 3),
                "avg_gap": round(gap_sum[k] / fail_count[k], 4),
            }
    return summary


def _parameter_sensitivity_compact(dim_analysis: dict) -> dict:
    """Reduce dim_analysis to compact 'best_value + spread' per dim."""
    out = {}
    for dim_key, by_value in dim_analysis.items():
        if not by_value:
            continue
        # Pick best value by avg_obj
        ranked = sorted(by_value.items(), key=lambda kv: kv[1].get("avg_obj", 0), reverse=True)
        best_val, best_stats = ranked[0]
        worst_stats = ranked[-1][1]
        spread = best_stats.get("avg_obj", 0) - worst_stats.get("avg_obj", 0)
        out[dim_key] = {
            "best_value": best_val,
            "best_avg_obj": round(best_stats.get("avg_obj", 0), 2),
            "spread": round(spread, 2),  # high spread = sensitive parameter
            "n_values_tested": len(by_value),
        }
    return out


def build_compact_payload(
    *,
    iter_dir: Path,
    mode: str,                          # "normal" | "repair" | "regression"
    iteration: int,
    target: str,
    gate_config: dict,
    current_search_space: dict,
    previous_search_space: Optional[dict] = None,
    last_patch: Optional[dict] = None,
    last_error: Optional[dict] = None,
    regression_report: Optional[dict] = None,
    warnings: Optional[list[str]] = None,
) -> dict:
    """Assemble a compact summary for Claude. Skip None fields cleanly."""
    iter_dir = Path(iter_dir)
    best_summary = _load_json(iter_dir / "best_summary.json") or {}
    llm_summary = _load_json(iter_dir / "summary_for_llm.json") or {}

    best_trial = llm_summary.get("best_trial", {})
    top_trials_full = llm_summary.get("top_5_trials", [])
    dim_analysis = llm_summary.get("dim_analysis", {})

    # Compact best_trial
    if best_trial:
        best_compact = {
            "trial_id": best_trial.get("trial_id"),
            "params": best_trial.get("params", {}),
            "train": {
                "n": best_trial.get("train", {}).get("n_trades", 0),
                "wr": round(best_trial.get("train", {}).get("win_rate", 0), 4),
                "avg_ret": round(best_trial.get("train", {}).get("avg_return_pct", 0), 4),
                "pf": round(best_trial.get("train", {}).get("profit_factor", 0), 4),
                "dd": round(best_trial.get("train", {}).get("max_drawdown", 0), 4),
                "gates": best_trial.get("train", {}).get("gates_passed", 0),
            },
            "validation": {
                "n": best_trial.get("validation", {}).get("n_trades", 0),
                "wr": round(best_trial.get("validation", {}).get("win_rate", 0), 4),
                "avg_ret": round(best_trial.get("validation", {}).get("avg_return_pct", 0), 4),
                "pf": round(best_trial.get("validation", {}).get("profit_factor", 0), 4),
                "dd": round(best_trial.get("validation", {}).get("max_drawdown", 0), 4),
                "gates": best_trial.get("validation", {}).get("gates_passed", 0),
            },
            "overfit_warning": best_trial.get("overfit_warning", False),
        }
        # cat3 metrics
        cat3 = best_trial.get("validation", {}).get("cat_metrics", {}).get("cat_3_packaging")
        if cat3:
            best_compact["cat3"] = {
                "n": cat3.get("n_trades", 0),
                "wr": round(cat3.get("win_rate", 0), 4),
                "pf": round(cat3.get("profit_factor", 0), 4),
                "dd": round(cat3.get("max_drawdown", 0), 4),
                "gates": cat3.get("gates_passed", 0),
            }
    else:
        best_compact = {}

    # Compact top trials (10) — only params + key val metrics
    top_trials = top_trials_full[:10]
    top_compact = [
        {
            "params": t.get("params", {}),
            "obj": t.get("objective", 0),
            "val_n": t.get("val_n", 0),
            "val_wr": t.get("val_wr", 0),
            "val_pf": t.get("val_pf", 0),
            "val_dd": t.get("val_dd", 0),
            "val_gates": t.get("val_gates", 0),
            "cat3_gates": t.get("cat3_gates", 0),
        }
        for t in top_trials
    ]

    # Try to load bottom 5 from runs CSV (sort ascending by objective)
    bottom_compact = []
    runs_csv = iter_dir / "optimization_runs.csv"
    if runs_csv.exists():
        try:
            df = pd.read_csv(runs_csv, encoding="utf-8-sig")
            bot = df.sort_values("objective_score", ascending=True).head(5)
            for _, row in bot.iterrows():
                bottom_compact.append({
                    "obj": round(float(row["objective_score"]), 2),
                    "val_n": int(row.get("val_n", 0)),
                    "val_wr": round(float(row.get("val_wr", 0)), 4),
                    "val_pf": round(float(row.get("val_pf", 0)), 4),
                    "val_dd": round(float(row.get("val_dd", 0)), 4),
                    "val_gates": int(row.get("val_gates", 0)),
                })
        except Exception:
            pass

    # train/val gap (overfit hint)
    train_val_gap = {}
    if best_compact:
        t = best_compact.get("train", {})
        v = best_compact.get("validation", {})
        train_val_gap = {
            "wr_gap": round(t.get("wr", 0) - v.get("wr", 0), 4),
            "avg_ret_gap": round(t.get("avg_ret", 0) - v.get("avg_ret", 0), 4),
            "pf_gap": round(t.get("pf", 0) - v.get("pf", 0), 4),
        }

    payload = {
        "iteration": iteration,
        "target": target,
        "mode": mode,
        "gate_config": gate_config,
        "current_search_space": current_search_space,
    }
    if previous_search_space:
        payload["previous_search_space"] = previous_search_space

    payload["best_trial"] = best_compact
    payload["top_trials"] = top_compact
    if bottom_compact:
        payload["bottom_trials"] = bottom_compact
    payload["failed_gates_summary"] = _failed_gates_summary(top_compact, gate_config)
    payload["train_validation_gap"] = train_val_gap
    payload["parameter_sensitivity"] = _parameter_sensitivity_compact(dim_analysis)

    if last_patch:
        payload["last_patch"] = last_patch
    if last_error:
        payload["last_error"] = last_error
    if regression_report:
        payload["regression_report"] = regression_report
    payload["warnings"] = warnings or []

    # Convergence info (small)
    if "convergence" in llm_summary:
        c = llm_summary["convergence"]
        payload["convergence"] = {
            "stagnation_trials": c.get("stagnation_trials", 0),
            "total_trials": c.get("total_trials", 0),
        }

    return payload
