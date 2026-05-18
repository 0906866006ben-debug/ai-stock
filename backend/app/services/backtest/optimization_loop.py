"""Closed-loop state machine: backtest → summarize → advise → validate → apply.

States: INIT → RUN_BACKTEST → BUILD_SUMMARY → DETECT_REGRESSION → CALL_ADVISOR
        → VALIDATE_PATCH → CHECK_STOP → (loop) or STOP

On RUN_BACKTEST exception: REPAIR mode → CALL_ADVISOR(mode=repair) → re-run

This module is OPTIMIZER-AGNOSTIC: it shells out to the existing optimization.py
infrastructure (importing run_optimization + load_search_space) but adds the
LLM-in-the-loop layer.
"""
from __future__ import annotations

import csv
import json
import logging
import shutil
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import yaml

from backend.app.services.backtest.llm_search_space_advisor import (
    AdvisorAPIError,
    AdvisorConfigError,
    AdvisorCallResult,
)
from backend.app.services.backtest.optimization_summary import build_compact_payload
from backend.app.services.backtest.optimizer import (
    derive_recommendation,
    run_optimization,
    write_best_params,
    write_best_summary,
    write_runs_csv,
    write_summary_for_llm,
    write_validation_report,
)
from backend.app.services.backtest.optimizer_config import (
    GateConfig,
    OptimizerConfig,
    TrialResult,
)
from backend.app.services.backtest.search_space_validator import (
    ClaudeResponse,
    ValidationResult,
    load_bounds_config,
    to_rules_dotted_paths,
    validate,
    weight_patch_to_overrides,
)

logger = logging.getLogger(__name__)


@dataclass
class LoopConfig:
    target: str = "cat3"
    max_iterations: int = 10
    trials_per_iter: int = 50
    seed: int = 42
    stop_on_success: bool = True
    stagnation_iters: int = 3
    min_improvement: float = 5.0
    repair_attempts: int = 3
    rollback_on_regression: bool = False
    start_date: str = "2022-11-01"
    end_date: str = "2026-05-15"
    db_path: str = "backend/historical_data.db"
    output_dir: str = "artifacts/strategy_optimization"
    auto_dir: str = "artifacts/strategy_optimization/auto"
    candidate_types: list[str] = field(default_factory=lambda: ["起漲前觀察"])
    gates: GateConfig = field(default_factory=GateConfig)
    bounds_config_path: str = "backend/app/services/backtest/allowed_bounds.yaml"
    n_workers: int = 1
    universe_categories: list[str] = field(default_factory=list)


@dataclass
class IterationSnapshot:
    iter_num: int
    mode: str                  # normal | repair | regression
    best_objective: float
    val_gates: int
    cat3_gates: int
    val_n: int
    val_wr: float
    val_pf: float
    val_dd: float
    advisor_action: str
    advisor_confidence: float
    overfit_warning: bool
    regression: bool
    repair_attempts_used: int
    short_reason_codes: list[str]


# ───────────────────────────────────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────────────────────────────────

def _safe_log(msg: str) -> None:
    """Print to terminal in a sanitized way (no API key, no full prompts)."""
    print(msg, flush=True)


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(payload, f, sort_keys=False, allow_unicode=True)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, default=str)


def _redact(payload: dict) -> dict:
    """Defensive: strip any field that might leak API key."""
    forbidden = {"api_key", "anthropic_api_key", "x-api-key", "authorization"}
    return {k: v for k, v in payload.items() if k.lower() not in forbidden}


def _has_improvement(prev_best_obj: Optional[float], cur_best_obj: float, min_delta: float) -> bool:
    if prev_best_obj is None:
        return True
    return cur_best_obj > prev_best_obj + min_delta


def _detect_regression(prev: Optional[dict], cur: dict) -> Optional[dict]:
    """Return regression_report dict if regression detected."""
    if not prev:
        return None

    prev_obj = prev.get("best_obj", 0)
    cur_obj = cur.get("best_obj", 0)
    prev_pf = prev.get("val_pf", 0)
    cur_pf = cur.get("val_pf", 0)
    prev_dd = prev.get("val_dd", 0)
    cur_dd = cur.get("val_dd", 0)
    prev_n = prev.get("val_n", 0)
    cur_n = cur.get("val_n", 0)
    prev_gates = prev.get("val_gates", 0)
    cur_gates = cur.get("val_gates", 0)

    regression = False
    reasons = []

    if prev_obj > 0 and cur_obj < prev_obj * 0.85:
        regression = True
        reasons.append(f"obj drop {prev_obj:.1f}→{cur_obj:.1f} ({(cur_obj/prev_obj - 1)*100:.1f}%)")
    if prev_pf > 1.2 and cur_pf < prev_pf * 0.7:
        regression = True
        reasons.append(f"PF drop {prev_pf:.2f}→{cur_pf:.2f}")
    if prev_dd < 0 and cur_dd < prev_dd * 1.5:
        regression = True
        reasons.append(f"DD worsened {prev_dd*100:.1f}%→{cur_dd*100:.1f}%")
    if prev_n > 0 and cur_n < prev_n * 0.5:
        regression = True
        reasons.append(f"n_trades drop {prev_n}→{cur_n}")
    if cur_gates < prev_gates - 1:
        regression = True
        reasons.append(f"gates drop {prev_gates}→{cur_gates}")

    if not regression:
        return None
    return {
        "prev_best_obj": prev_obj,
        "cur_best_obj": cur_obj,
        "reasons": reasons,
    }


def _apply_patch_to_search_space(
    base_space: dict[str, list],
    cleaned: ClaudeResponse,
    parameter_mapping: dict,
) -> dict[str, list]:
    """Merge Claude's patch into current space. New keys override existing ones."""
    new_space = dict(base_space)
    translated = to_rules_dotted_paths(cleaned.next_search_space, parameter_mapping)
    new_space.update(translated)
    # Weights become single-value entries in search_space (under scoring.pre_breakout_weights.*)
    weight_overrides = weight_patch_to_overrides(cleaned.weight_patch)
    new_space.update(weight_overrides)
    return new_space


# ───────────────────────────────────────────────────────────────────────────
# Main loop
# ───────────────────────────────────────────────────────────────────────────

def run_closed_loop(
    *,
    loop_config: LoopConfig,
    advisor: Any,                             # ClaudeAdvisor | FakeAdvisor
    initial_search_space: dict[str, list],
) -> tuple[Optional[dict], list[IterationSnapshot]]:
    """Run the full closed-loop optimization. Returns (global_best_iter_snapshot, history)."""
    bounds_config = load_bounds_config(loop_config.bounds_config_path)
    parameter_mapping = bounds_config.get("parameter_mapping", {})

    auto_dir = Path(loop_config.auto_dir)
    auto_dir.mkdir(parents=True, exist_ok=True)
    log_path = auto_dir / "auto_optimize_log.txt"
    history_csv = auto_dir / "all_iterations_summary.csv"

    history: list[IterationSnapshot] = []
    current_space = dict(initial_search_space)
    previous_space: Optional[dict] = None
    global_best: Optional[dict] = None     # holds {best_obj, val_gates, etc., iter_num}
    prev_iter_snapshot: Optional[dict] = None
    last_patch: Optional[dict] = None
    last_error: Optional[dict] = None
    consecutive_api_failures = 0
    stagnation_counter = 0

    iter_num = 0
    while iter_num < loop_config.max_iterations:
        iter_num += 1
        mode = "normal"
        repair_attempts_used = 0
        regression_report: Optional[dict] = None

        # ── Inner loop for repair retries ─────────────────────────────────
        while True:
            iter_dir = Path(loop_config.output_dir) / f"iter_{iter_num:02d}"
            iter_dir.mkdir(parents=True, exist_ok=True)

            # Save the search space we are about to use
            _write_yaml(iter_dir / "search_space_used.yaml", {"search_space": current_space})

            try:
                _safe_log(f"[iter {iter_num:02d}] running {loop_config.trials_per_iter} trials (mode={mode})...")

                # ── RUN_BACKTEST (in-process) ─────────────────────────────
                opt_config = OptimizerConfig(
                    target=loop_config.target,
                    method="random",
                    max_trials=loop_config.trials_per_iter,
                    train_split=0.7,
                    top_k=10,
                    seed=loop_config.seed + iter_num,
                    start_date=loop_config.start_date,
                    end_date=loop_config.end_date,
                    db_path=loop_config.db_path,
                    output_dir=loop_config.output_dir,
                    candidate_types=loop_config.candidate_types,
                    gates=loop_config.gates,
                    n_workers=loop_config.n_workers,
                    universe_categories=loop_config.universe_categories,
                )

                results, best = run_optimization(opt_config, current_space)

                if not results or best is None:
                    raise RuntimeError("No valid trials produced; check data or search space")

                # Persist iter artifacts
                write_runs_csv(iter_dir / "optimization_runs.csv", results)
                write_best_params(iter_dir / "best_params.yaml", best.params)
                recommendation = derive_recommendation(best, loop_config.target)
                write_best_summary(iter_dir / "best_summary.json", best, opt_config, len(results), recommendation)
                top_k = sorted(results, key=lambda r: r.objective_score, reverse=True)[:10]
                write_validation_report(iter_dir / "validation_report.csv", top_k)
                write_summary_for_llm(
                    iter_dir / "summary_for_llm.json",
                    results=results,
                    best=best,
                    config=opt_config,
                    search_space=current_space,
                    iteration=iter_num,
                    recommendation=recommendation,
                )
                last_error = None  # success
                break  # exit repair inner loop

            except Exception as exc:
                repair_attempts_used += 1
                last_error = {
                    "type": type(exc).__name__,
                    "message": str(exc)[:300],
                    "stage": "RUN_BACKTEST",
                    "attempt": repair_attempts_used,
                }
                _write_json(iter_dir / "repair_log.json", last_error)
                _safe_log(f"[iter {iter_num:02d}] backtest failed: {type(exc).__name__} — repair attempt {repair_attempts_used}")

                if repair_attempts_used > loop_config.repair_attempts:
                    _safe_log(f"[iter {iter_num:02d}] repair attempts exceeded ({loop_config.repair_attempts}); stopping")
                    return global_best, history

                # Call Claude in repair mode
                payload = build_compact_payload(
                    iter_dir=iter_dir,
                    mode="repair",
                    iteration=iter_num,
                    target=loop_config.target,
                    gate_config=asdict(loop_config.gates),
                    current_search_space=current_space,
                    previous_search_space=previous_space,
                    last_patch=last_patch,
                    last_error=last_error,
                )
                _write_json(iter_dir / "claude_request.json", _redact(payload))

                try:
                    call_result = advisor.advise(payload)
                    _write_json(iter_dir / "claude_response.json", {"raw_text": call_result.raw_text})
                    consecutive_api_failures = 0
                except (AdvisorAPIError, AdvisorConfigError) as api_exc:
                    consecutive_api_failures += 1
                    _safe_log(f"[iter {iter_num:02d}] Claude API failed: {api_exc}")
                    if consecutive_api_failures >= 3:
                        return global_best, history
                    continue

                validation = validate(call_result.raw_text, bounds_config)
                _write_json(iter_dir / "advisor_warnings.json", {
                    "warnings": validation.warnings,
                    "errors": validation.errors,
                    "dropped_keys": validation.dropped_keys,
                })

                if not validation.valid or validation.cleaned is None:
                    _safe_log(f"[iter {iter_num:02d}] repair patch invalid; aborting iteration")
                    return global_best, history

                current_space = _apply_patch_to_search_space(
                    current_space, validation.cleaned, parameter_mapping
                )
                _write_yaml(iter_dir / "next_search_space.yaml", {"search_space": current_space})
                last_patch = asdict(validation.cleaned)
                mode = "repair"
                # Loop back to retry RUN_BACKTEST with patched space

        # ── BUILD compact payload + DETECT regression ─────────────────────
        cur_iter_summary = {
            "best_obj": best.objective_score,
            "val_gates": best.validation.gates_passed,
            "cat3_gates": best.validation.cat_metrics.get("cat_3_packaging").gates_passed
                if best.validation.cat_metrics.get("cat_3_packaging") else 0,
            "val_n": best.validation.n_trades,
            "val_wr": best.validation.win_rate,
            "val_pf": best.validation.profit_factor,
            "val_dd": best.validation.max_drawdown,
        }

        regression_report = _detect_regression(prev_iter_snapshot, cur_iter_summary)
        if regression_report:
            mode = "regression"
            _write_json(iter_dir / "regression_report.json", regression_report)
            if loop_config.rollback_on_regression:
                _safe_log(f"[iter {iter_num:02d}] regression detected; rolling back search space")

        # Degenerate-trial guard: reject promotion when sample is reward-hack
        # thin (n<3, PF>=20 = almost certainly n-too-small, or overfit warning).
        # Phase 9.8: lowered min_val_n threshold to support small universes
        # (cat3 = 7 stocks → real val window is naturally ≤ 5 trades).
        min_val_n = max(3, loop_config.gates.min_trades // 10)
        is_degenerate = (
            cur_iter_summary["val_n"] < min_val_n
            or cur_iter_summary["val_pf"] >= 20.0   # PF > 20 ≈ n too small or single freak trade
            or best.overfit_warning
        )

        improvement = _has_improvement(
            global_best.get("best_obj") if global_best else None,
            best.objective_score,
            loop_config.min_improvement,
        )
        if improvement and not is_degenerate:
            global_best = {
                **cur_iter_summary,
                "iter_num": iter_num,
                "best_params": best.params,
                "best_summary_path": str(iter_dir / "best_summary.json"),
                "overfit_warning": best.overfit_warning,
            }
            stagnation_counter = 0
        else:
            stagnation_counter += 1
            if is_degenerate:
                _safe_log(
                    f"[iter {iter_num:02d}] degenerate trial rejected "
                    f"(val_n={cur_iter_summary['val_n']}, "
                    f"val_pf={cur_iter_summary['val_pf']:.2f}, "
                    f"overfit={best.overfit_warning})"
                )

        marker = " ↑improvement" if (improvement and not is_degenerate) else ""
        if best.success and not best.overfit_warning:
            marker = " ⭐ SUCCESS"

        _safe_log(
            f"[iter {iter_num:02d}] best_obj={best.objective_score:.1f} "
            f"val_cat3_gates={cur_iter_summary['cat3_gates']}/4 "
            f"val_n={cur_iter_summary['val_n']} "
            f"val_pf={cur_iter_summary['val_pf']:.2f} "
            f"val_dd={cur_iter_summary['val_dd']*100:.1f}%{marker}"
        )

        # ── Check stop conditions BEFORE calling advisor for next round ───
        if loop_config.stop_on_success and best.success and not best.overfit_warning:
            _safe_log(f"[STOP] stop_on_success triggered at iter {iter_num}")
            history.append(IterationSnapshot(
                iter_num=iter_num, mode=mode,
                best_objective=best.objective_score,
                val_gates=cur_iter_summary["val_gates"],
                cat3_gates=cur_iter_summary["cat3_gates"],
                val_n=cur_iter_summary["val_n"],
                val_wr=cur_iter_summary["val_wr"],
                val_pf=cur_iter_summary["val_pf"],
                val_dd=cur_iter_summary["val_dd"],
                advisor_action="(skipped: success)",
                advisor_confidence=0.0,
                overfit_warning=best.overfit_warning,
                regression=regression_report is not None,
                repair_attempts_used=repair_attempts_used,
                short_reason_codes=[],
            ))
            break

        def _append_terminal_snapshot(reason: str) -> None:
            history.append(IterationSnapshot(
                iter_num=iter_num, mode=mode,
                best_objective=best.objective_score,
                val_gates=cur_iter_summary["val_gates"],
                cat3_gates=cur_iter_summary["cat3_gates"],
                val_n=cur_iter_summary["val_n"],
                val_wr=cur_iter_summary["val_wr"],
                val_pf=cur_iter_summary["val_pf"],
                val_dd=cur_iter_summary["val_dd"],
                advisor_action=f"(skipped: {reason})",
                advisor_confidence=0.0,
                overfit_warning=best.overfit_warning,
                regression=regression_report is not None,
                repair_attempts_used=repair_attempts_used,
                short_reason_codes=[],
            ))

        if stagnation_counter >= loop_config.stagnation_iters:
            _safe_log(f"[STOP] stagnation: no improvement for {stagnation_counter} iterations")
            _append_terminal_snapshot("stagnation")
            break

        if iter_num >= loop_config.max_iterations:
            _append_terminal_snapshot("max_iterations")
            break  # final iteration just ran

        # ── CALL_ADVISOR for next iteration ───────────────────────────────
        payload = build_compact_payload(
            iter_dir=iter_dir,
            mode=mode,
            iteration=iter_num,
            target=loop_config.target,
            gate_config=asdict(loop_config.gates),
            current_search_space=current_space,
            previous_search_space=previous_space,
            last_patch=last_patch,
            last_error=last_error,
            regression_report=regression_report,
        )
        _write_json(iter_dir / "claude_request.json", _redact(payload))

        try:
            call_result = advisor.advise(payload)
            _write_json(iter_dir / "claude_response.json", {"raw_text": call_result.raw_text})
            consecutive_api_failures = 0
        except (AdvisorAPIError, AdvisorConfigError) as api_exc:
            consecutive_api_failures += 1
            _safe_log(f"[iter {iter_num:02d}] Claude API failed: {api_exc}")
            if consecutive_api_failures >= 3:
                _safe_log("[STOP] 3 consecutive Claude API failures")
                break
            continue

        # ── VALIDATE patch ────────────────────────────────────────────────
        validation = validate(call_result.raw_text, bounds_config)
        _write_json(iter_dir / "advisor_warnings.json", {
            "warnings": validation.warnings,
            "errors": validation.errors,
            "dropped_keys": validation.dropped_keys,
        })

        if not validation.valid or validation.cleaned is None:
            _safe_log(f"[iter {iter_num:02d}] advisor returned invalid patch; using current space (no change)")
            last_patch = None
        else:
            cleaned = validation.cleaned
            history.append(IterationSnapshot(
                iter_num=iter_num, mode=mode,
                best_objective=best.objective_score,
                val_gates=cur_iter_summary["val_gates"],
                cat3_gates=cur_iter_summary["cat3_gates"],
                val_n=cur_iter_summary["val_n"],
                val_wr=cur_iter_summary["val_wr"],
                val_pf=cur_iter_summary["val_pf"],
                val_dd=cur_iter_summary["val_dd"],
                advisor_action=cleaned.action,
                advisor_confidence=cleaned.confidence,
                overfit_warning=best.overfit_warning,
                regression=regression_report is not None,
                repair_attempts_used=repair_attempts_used,
                short_reason_codes=cleaned.short_reason_codes,
            ))

            _safe_log(
                f"[iter {iter_num:02d}] advisor={cleaned.action} "
                f"conf={cleaned.confidence:.2f} "
                f"codes={cleaned.short_reason_codes}"
            )

            if cleaned.stop or cleaned.action == "stop":
                _safe_log("[STOP] advisor requested stop")
                break

            if cleaned.action == "rollback" and previous_space:
                current_space = dict(previous_space)
                _write_yaml(iter_dir / "next_search_space.yaml", {"search_space": current_space})
            else:
                previous_space = dict(current_space)
                current_space = _apply_patch_to_search_space(
                    current_space, cleaned, parameter_mapping
                )
                _write_yaml(iter_dir / "next_search_space.yaml", {"search_space": current_space})

            last_patch = asdict(cleaned)

        prev_iter_snapshot = cur_iter_summary

    # ── Persist global outputs ────────────────────────────────────────────
    if global_best:
        _write_yaml(auto_dir / "global_best_params.yaml", {"surge_candidate_best": global_best.get("best_params", {})})
        _write_json(auto_dir / "global_best_summary.json", global_best)

    if history:
        with (auto_dir / "all_iterations_summary.csv").open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "iter_num", "mode", "best_objective", "val_gates", "cat3_gates",
                "val_n", "val_wr", "val_pf", "val_dd",
                "advisor_action", "advisor_confidence", "overfit_warning",
                "regression", "repair_attempts_used", "short_reason_codes",
            ])
            writer.writeheader()
            for snap in history:
                row = asdict(snap)
                row["short_reason_codes"] = "|".join(snap.short_reason_codes)
                writer.writerow(row)

    return global_best, history
