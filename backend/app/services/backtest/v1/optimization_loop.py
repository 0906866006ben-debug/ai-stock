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
    bounds_config_path: str = "backend/app/services/backtest/v1/allowed_bounds.yaml"
    n_workers: int = 1
    universe_categories: list[str] = field(default_factory=list)
    sampler_method: str = "adaptive"
    min_entry_tier: int = 1


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


def _summarize_trial(trial: TrialResult) -> dict:
    val = trial.validation
    cat3 = val.cat_metrics.get("cat_3_packaging")
    return {
        "best_obj": trial.objective_score,
        "val_gates": val.gates_passed,
        "cat3_gates": cat3.gates_passed if cat3 else 0,
        "val_n": val.n_trades,
        "val_wr": val.win_rate,
        "val_pf": val.profit_factor,
        "val_dd": val.max_drawdown,
    }


def _is_degenerate_trial(trial: TrialResult, gates: GateConfig) -> bool:
    """Return True when a trial should not be promoted as global best."""
    # Small universes can naturally produce few validation trades, so keep this
    # much softer than the real min_trades gate while rejecting reward hacks.
    min_val_n = max(3, gates.min_trades // 10)
    return (
        trial.validation.n_trades < min_val_n
        or trial.validation.profit_factor >= 20.0
        or trial.overfit_warning
    )


def _select_promotable_result(
    results: list[TrialResult],
    gates: GateConfig,
) -> Optional[TrialResult]:
    """Pick the best non-degenerate trial from an iteration, if one exists."""
    candidates = [r for r in results if not _is_degenerate_trial(r, gates)]
    if not candidates:
        return None
    return max(candidates, key=lambda r: r.objective_score)


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

    # Phase 9.8 speedup: build ONE worker pool that survives across iters so
    # OHLCV cache + feature cache stay warm. Without this, every iter rebuilds
    # the cache (~3 min wasted per iter × 20 iters = 1 hr saved).
    shared_pool = None
    if loop_config.n_workers > 1:
        from multiprocessing import Pool
        from backend.app.services.sector_service import list_ai_tech_codes, list_codes_by_category
        # Resolve universe once (matches _resolve_universe in optimizer.py)
        if loop_config.universe_categories:
            codes: set[str] = set()
            for cat_key in loop_config.universe_categories:
                codes |= list_codes_by_category(cat_key)
            universe = sorted(codes)
        else:
            universe = sorted(list_ai_tech_codes())
        from backend.app.services.backtest.optimizer import _init_worker
        shared_pool = Pool(
            processes=loop_config.n_workers,
            initializer=_init_worker,
            initargs=(loop_config.db_path, universe, loop_config.start_date, loop_config.end_date),
        )
        _safe_log(f"[init] shared worker pool started ({loop_config.n_workers} workers, universe={len(universe)} stocks)")

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
                import time as _time
                iter_start = _time.time()
                trials_total = loop_config.trials_per_iter
                _safe_log(f"[iter {iter_num:02d}] starting {trials_total} trials (mode={mode}, workers={loop_config.n_workers})...")

                # ── RUN_BACKTEST (in-process) ─────────────────────────────
                opt_config = OptimizerConfig(
                    target=loop_config.target,
                    method=loop_config.sampler_method,
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
                    min_entry_tier=loop_config.min_entry_tier,
                )

                # Progress callback: print line every trial with running best + ETA
                progress_state = {"completed": 0, "start": _time.time(), "iter_num": iter_num, "total": trials_total}
                def _on_trial(result, best_so_far, is_best):
                    progress_state["completed"] += 1
                    n = progress_state["completed"]
                    elapsed = _time.time() - progress_state["start"]
                    rate = n / elapsed if elapsed > 0 else 0
                    eta_sec = (progress_state["total"] - n) / rate if rate > 0 else 0
                    marker = " ⭐" if is_best else ""
                    val = result.validation
                    cat3 = val.cat_metrics.get("cat_3_packaging")
                    cat3_g = cat3.gates_passed if cat3 else 0
                    eta_str = f"{int(eta_sec//60)}m{int(eta_sec%60):02d}s" if eta_sec else "—"
                    _safe_log(
                        f"  iter {progress_state['iter_num']:02d} [{n:3d}/{progress_state['total']}] "
                        f"obj={result.objective_score:>7.1f} "
                        f"val_n={val.n_trades:>2d} pf={val.profit_factor:>5.2f} dd={val.max_drawdown*100:>+6.1f}% "
                        f"cat3g={cat3_g}/4 best_obj={best_so_far.objective_score:>7.1f}{marker}  ETA {eta_str}"
                    )

                results, best = run_optimization(opt_config, current_space,
                                                  progress_callback=_on_trial,
                                                  external_pool=shared_pool)
                iter_elapsed = _time.time() - iter_start
                _safe_log(f"[iter {iter_num:02d}] done in {int(iter_elapsed//60)}m{int(iter_elapsed%60):02d}s "
                          f"({len(results)} trials, avg {iter_elapsed/max(1,len(results)):.1f}s/trial)")

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
        cur_iter_summary = _summarize_trial(best)

        regression_report = _detect_regression(prev_iter_snapshot, cur_iter_summary)
        if regression_report:
            mode = "regression"
            _write_json(iter_dir / "regression_report.json", regression_report)
            if loop_config.rollback_on_regression:
                _safe_log(f"[iter {iter_num:02d}] regression detected; rolling back search space")

        # Degenerate-trial guard: reject promotion when the top objective is a
        # reward hack, but do not throw away the whole iteration if another
        # candidate is stable enough to become the global baseline.
        is_degenerate = _is_degenerate_trial(best, loop_config.gates)
        promoted = _select_promotable_result(results, loop_config.gates) if is_degenerate else best
        promoted_summary = _summarize_trial(promoted) if promoted else None
        improvement = (
            promoted is not None
            and _has_improvement(
                global_best.get("best_obj") if global_best else None,
                promoted.objective_score,
                loop_config.min_improvement,
            )
        )
        if improvement and promoted_summary is not None and promoted is not None:
            best_summary_path = iter_dir / "best_summary.json"
            if promoted.trial_id != best.trial_id:
                promoted_recommendation = derive_recommendation(promoted, loop_config.target)
                write_best_params(iter_dir / "promoted_params.yaml", promoted.params)
                write_best_summary(
                    iter_dir / "promoted_summary.json",
                    promoted,
                    opt_config,
                    len(results),
                    promoted_recommendation,
                )
                best_summary_path = iter_dir / "promoted_summary.json"
            global_best = {
                **promoted_summary,
                "iter_num": iter_num,
                "best_params": promoted.params,
                "best_summary_path": str(best_summary_path),
                "overfit_warning": promoted.overfit_warning,
                "promoted_trial_id": promoted.trial_id,
                "top_trial_id": best.trial_id,
            }
            stagnation_counter = 0
        else:
            stagnation_counter += 1

        if is_degenerate:
            if promoted is None:
                suffix = "; no promotable trial"
            elif improvement:
                suffix = f"; promoting robust trial #{promoted.trial_id}"
            else:
                suffix = f"; robust trial #{promoted.trial_id} did not improve global best"
            _safe_log(
                f"[iter {iter_num:02d}] top trial rejected as degenerate "
                f"(trial={best.trial_id}, val_n={cur_iter_summary['val_n']}, "
                f"val_pf={cur_iter_summary['val_pf']:.2f}, "
                f"overfit={best.overfit_warning}){suffix}"
            )

        marker = " ↑improvement" if improvement else ""
        if promoted is not None and promoted.trial_id != best.trial_id and improvement:
            marker += f" (promoted robust trial #{promoted.trial_id})"
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

    # ── Cleanup shared worker pool (Phase 9.8 speedup) ───────────────────
    if shared_pool is not None:
        try:
            shared_pool.close()
            shared_pool.join()
        except Exception as exc:
            logger.warning("shared pool cleanup error: %s", exc)
            try:
                shared_pool.terminate()
            except Exception:
                pass

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
