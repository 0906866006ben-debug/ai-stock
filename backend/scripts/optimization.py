"""Strategy Parameter Optimizer CLI.

Usage:
    python -m backend.scripts.optimization --target cat3 --max-trials 200
    python -m backend.scripts.optimization --target all --method adaptive --max-trials 500

This script runs entirely locally without LLM involvement per-iteration. It:
  1. Loads the search space (default backend/.../optimizer_search_space.yaml)
  2. Samples params, builds override YAML, runs train+val backtest in-process
  3. Scores via composite objective, tracks best, stops early on success
  4. Outputs:
       artifacts/strategy_optimization/optimization_runs.csv
       artifacts/strategy_optimization/best_params.yaml
       artifacts/strategy_optimization/best_summary.json
       artifacts/strategy_optimization/validation_report.csv

Does NOT auto-apply best_params to production rules_v1.yaml.
Outputs a short status line per trial and a 12-line final report only.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

from backend.app.services.backtest.optimizer import (
    OBJECTIVE_FORMULA,
    derive_recommendation,
    load_search_space,
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


DEFAULT_SEARCH_SPACE = Path(__file__).resolve().parent.parent / "app" / "services" / "backtest" / "v1" / "optimizer_search_space.yaml"


def _print_progress(result: TrialResult, best: TrialResult, is_best: bool) -> None:
    """One concise status line per trial."""
    val = result.validation
    cat3 = val.cat_metrics.get("cat_3_packaging")
    cat3_g = cat3.gates_passed if cat3 else 0
    marker = " ⭐ best" if is_best else ""
    print(
        f"[{result.trial_id:04d}] obj={result.objective_score:>8.2f}  "
        f"val_gates={val.gates_passed}/4  cat3_gates={cat3_g}/4  "
        f"val_n={val.n_trades:>3}  val_wr={val.win_rate:.2f}  "
        f"val_pf={val.profit_factor:.2f}  val_dd={val.max_drawdown*100:>6.2f}%"
        f"{marker}",
        flush=True,
    )


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Strategy parameter optimizer")
    parser.add_argument("--target", choices=["cat3", "all"], default="cat3")
    parser.add_argument("--method", choices=["random", "grid", "adaptive"], default="adaptive")
    parser.add_argument("--max-trials", type=int, default=200)
    parser.add_argument("--start", default="2022-11-01")
    parser.add_argument("--end", default="2026-05-15")
    parser.add_argument("--train-split", type=float, default=0.7)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--db", default="backend/historical_data.db")
    parser.add_argument("--output-dir", default="artifacts/strategy_optimization")
    parser.add_argument("--iteration", type=int, default=1,
                        help="Iteration number (1, 2, 3...). Output goes to iter_NN/ subdirectory.")
    parser.add_argument("--search-space", default=str(DEFAULT_SEARCH_SPACE))
    parser.add_argument("--stocks", nargs="*", help="Override universe with explicit codes")
    parser.add_argument("--candidate-types", nargs="+", default=["起漲前觀察"])
    parser.add_argument("--workers", type=int, default=1,
                        help="Parallel trial workers. 1 = sequential.")
    parser.add_argument("--min-trades", type=int, default=30)
    parser.add_argument("--min-win-rate", type=float, default=0.45)
    parser.add_argument("--min-profit-factor", type=float, default=1.05)
    parser.add_argument("--max-drawdown-pct", type=float, default=-0.15)
    parser.add_argument("--min-entry-tier", type=int, choices=[1, 2, 3], default=1,
                        help="Phase 11: minimum tier to enter (1=CORE, 2=QUALITY, 3=PREMIUM)")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    gates = GateConfig(
        min_trades=args.min_trades,
        min_win_rate=args.min_win_rate,
        min_profit_factor=args.min_profit_factor,
        max_drawdown_pct=args.max_drawdown_pct,
    )

    config = OptimizerConfig(
        target=args.target,
        method=args.method,
        max_trials=args.max_trials,
        train_split=args.train_split,
        top_k=args.top_k,
        seed=args.seed,
        start_date=args.start,
        end_date=args.end,
        db_path=args.db,
        output_dir=args.output_dir,
        universe=args.stocks or [],
        candidate_types=args.candidate_types,
        gates=gates,
        n_workers=max(1, args.workers),
        min_entry_tier=args.min_entry_tier,
    )

    print("=" * 80)
    print(f" Strategy Parameter Optimization")
    print(f" target={args.target} | method={args.method} | max_trials={args.max_trials} | workers={max(1, args.workers)}")
    print(f" date_range={args.start} ~ {args.end} | train_split={args.train_split}")
    print(f" gates: n>={args.min_trades}  wr>={args.min_win_rate}  pf>={args.min_profit_factor}  dd>={args.max_drawdown_pct}")
    print(f" min_entry_tier={args.min_entry_tier}")
    print("=" * 80)

    search_space = load_search_space(args.search_space)

    try:
        results, best = run_optimization(
            config, search_space, progress_callback=_print_progress
        )
    except Exception as exc:
        print(f"\nFATAL: optimization aborted — {exc}")
        return 2

    if not results:
        print("\nNo successful trials. Check data store and search space.")
        return 1

    # ── Persist outputs ─────────────────────────────────────────────────────
    # Each iteration goes into its own subdirectory; AI reads summary_for_llm.json
    iter_dir = Path(args.output_dir) / f"iter_{args.iteration:02d}"
    iter_dir.mkdir(parents=True, exist_ok=True)

    runs_csv = iter_dir / "optimization_runs.csv"
    write_runs_csv(runs_csv, results)

    best_params_yaml = iter_dir / "best_params.yaml"
    best_summary_json = iter_dir / "best_summary.json"
    validation_csv = iter_dir / "validation_report.csv"
    llm_summary_json = iter_dir / "summary_for_llm.json"

    if best is None:
        print("\nNo valid trial result; nothing to persist.")
        return 1

    write_best_params(best_params_yaml, best.params)
    top_k = sorted(results, key=lambda r: r.objective_score, reverse=True)[: args.top_k]
    write_validation_report(validation_csv, top_k)

    recommendation = derive_recommendation(best, args.target)
    write_best_summary(best_summary_json, best, config, len(results), recommendation)

    # AI-friendly compact summary (this is what user pastes to chat)
    write_summary_for_llm(
        llm_summary_json,
        results=results,
        best=best,
        config=config,
        search_space=search_space,
        iteration=args.iteration,
        recommendation=recommendation,
    )

    # ── Final report ────────────────────────────────────────────────────────
    val = best.validation
    train = best.train
    cat3 = val.cat_metrics.get("cat_3_packaging")
    all_cats = list(val.cat_metrics.values())
    all_cats_passed = sum(1 for c in all_cats if c.gates_passed == 4)

    print()
    print("=" * 80)
    print(" Final Report")
    print("=" * 80)
    print(f" iteration:           #{args.iteration}")
    print(f" target:              {args.target}")
    print(f" method:              {args.method}")
    print(f" trials_run:          {len(results)}")
    print(f" best_trial_id:       #{best.trial_id}")
    print(f" best_objective:      {best.objective_score:.2f}")
    print(f" cat3 gates:          {cat3.gates_passed if cat3 else 0}/4"
          f"   ({'✅' if cat3 and cat3.gates_passed == 4 else '❌'})")
    print(f" all-cat gates:       {all_cats_passed}/{len(all_cats)} categories fully pass")
    print(f" train metrics:       n={train.n_trades}  wr={train.win_rate:.2%}  avg={train.avg_return_pct*100:.2f}%  pf={train.profit_factor:.2f}  dd={train.max_drawdown*100:.2f}%")
    print(f" validation metrics:  n={val.n_trades}  wr={val.win_rate:.2%}  avg={val.avg_return_pct*100:.2f}%  pf={val.profit_factor:.2f}  dd={val.max_drawdown*100:.2f}%")
    print(f" overfit_warning:     {best.overfit_warning}")
    print(f" best_params path:    {best_params_yaml}")
    print(f" summary path:        {best_summary_json}")
    print(f" runs CSV:            {runs_csv}")
    print(f" validation report:   {validation_csv}")
    print(f" recommendation:      {recommendation}")
    print("=" * 80)
    print()
    print(f"📋 NEXT STEP: paste this file's content to your AI assistant for next-round tuning:")
    print(f"   {llm_summary_json}")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
