"""Closed-loop strategy optimizer CLI (Claude API in the loop).

Usage:
    .venv\\Scripts\\python.exe -m backend.scripts.auto_optimize \\
        --target cat3 \\
        --max-iterations 10 \\
        --trials-per-iter 50 \\
        --model claude-sonnet-4-6 \\
        --temperature 0.2 \\
        --seed 42

Per spec:
- API key is read from `ANTHROPIC_API_KEY` in backend/.env (never printed, never written to logs).
- Strict JSON-only patches from Claude; invalid patches are rejected or trigger repair.
- Core invariants (range_90d 10-30%, EMA transition, volume contraction) cannot be removed.
- Does NOT modify production rules_v1.yaml; uses a temporary override via the optimizer.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from backend.app.services.backtest.llm_search_space_advisor import (
    AdvisorConfigError,
    build_advisor,
)
from backend.app.services.backtest.optimization_loop import (
    LoopConfig,
    run_closed_loop,
)
from backend.app.services.backtest.optimizer import load_search_space
from backend.app.services.backtest.optimizer_config import GateConfig


DEFAULT_SEARCH_SPACE = (
    Path(__file__).resolve().parent.parent
    / "app" / "services" / "backtest" / "optimizer_search_space.yaml"
)
DEFAULT_BOUNDS = (
    Path(__file__).resolve().parent.parent
    / "app" / "services" / "backtest" / "allowed_bounds.yaml"
)


def _bool_env(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Closed-loop Claude-driven strategy optimizer",
    )
    parser.add_argument("--target", choices=["cat3", "all"], default="cat3")
    parser.add_argument("--max-iterations", type=int, default=10)
    parser.add_argument("--trials-per-iter", type=int, default=50)
    parser.add_argument("--model", default=None,
                        help="Override ANTHROPIC_MODEL (default: env var)")
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--start", default="2022-11-01")
    parser.add_argument("--end", default="2026-05-15")
    parser.add_argument("--db", default="backend/historical_data.db")
    parser.add_argument("--output-dir", default="artifacts/strategy_optimization")
    parser.add_argument("--auto-dir", default="artifacts/strategy_optimization/auto")
    parser.add_argument("--search-space", default=str(DEFAULT_SEARCH_SPACE))
    parser.add_argument("--bounds-config", default=str(DEFAULT_BOUNDS))
    parser.add_argument("--candidate-types", nargs="+", default=["起漲前觀察"])

    # Gate config
    parser.add_argument("--min-trades", type=int, default=30)
    parser.add_argument("--min-win-rate", type=float, default=0.45)
    parser.add_argument("--min-profit-factor", type=float, default=1.05)
    parser.add_argument("--max-drawdown-pct", type=float, default=-0.15)

    # Loop knobs
    parser.add_argument("--dry-run", action="store_true",
                        help="Use FakeAdvisor (no API call); auto-stops after iter 2")
    parser.add_argument("--stop-on-success", action="store_true", default=None)
    parser.add_argument("--no-stop-on-success", dest="stop_on_success",
                        action="store_false")
    parser.add_argument("--stagnation-iters", type=int, default=3)
    parser.add_argument("--min-improvement", type=float, default=5.0)
    parser.add_argument("--repair-attempts", type=int, default=2)
    parser.add_argument("--rollback-on-regression", action="store_true", default=None)
    parser.add_argument("--no-rollback-on-regression",
                        dest="rollback_on_regression", action="store_false")

    # Speedup knobs
    parser.add_argument("--workers", type=int, default=1,
                        help="Parallel trial workers (multiprocess). 1 = sequential (default)")
    parser.add_argument("--universe-from-target", action="store_true",
                        help="When target=cat3, narrow universe to cat_3_packaging only (4x faster)")
    parser.add_argument("--universe-categories", nargs="+", default=None,
                        help="Explicit AI tech category keys (e.g. cat_3_packaging cat_2_foundry)")

    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    # Load env (silent if .env is missing — env vars may be set externally)
    load_dotenv(Path("backend/.env"), override=False)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    # Resolve model + env-derived defaults
    model = args.model or os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    stop_on_success = (
        args.stop_on_success
        if args.stop_on_success is not None
        else _bool_env("AUTO_OPTIMIZE_STOP_ON_SUCCESS", True)
    )
    rollback_on_regression = (
        args.rollback_on_regression
        if args.rollback_on_regression is not None
        else _bool_env("AUTO_OPTIMIZE_ROLLBACK_ON_REGRESSION", False)
    )

    # ── Build advisor (or fake) ─────────────────────────────────────────────
    try:
        advisor = build_advisor(
            dry_run=args.dry_run,
            model=model,
            temperature=args.temperature,
        )
    except AdvisorConfigError as exc:
        print(f"FATAL: advisor configuration error — {exc}", file=sys.stderr)
        print("Set ANTHROPIC_API_KEY in backend/.env or environment.",
              file=sys.stderr)
        return 2

    # ── Load initial search space ───────────────────────────────────────────
    try:
        initial_space = load_search_space(args.search_space)
    except (FileNotFoundError, ValueError) as exc:
        print(f"FATAL: search space invalid — {exc}", file=sys.stderr)
        return 2

    # ── Assemble LoopConfig ─────────────────────────────────────────────────
    gates = GateConfig(
        min_trades=args.min_trades,
        min_win_rate=args.min_win_rate,
        min_profit_factor=args.min_profit_factor,
        max_drawdown_pct=args.max_drawdown_pct,
    )

    # Resolve universe categories (explicit list > --universe-from-target > full AI tech)
    if args.universe_categories:
        universe_cats = list(args.universe_categories)
    elif args.universe_from_target and args.target == "cat3":
        universe_cats = ["cat_3_packaging"]
    else:
        universe_cats = []

    loop_config = LoopConfig(
        target=args.target,
        max_iterations=args.max_iterations,
        trials_per_iter=args.trials_per_iter,
        seed=args.seed,
        stop_on_success=stop_on_success,
        stagnation_iters=args.stagnation_iters,
        min_improvement=args.min_improvement,
        repair_attempts=args.repair_attempts,
        rollback_on_regression=rollback_on_regression,
        start_date=args.start,
        end_date=args.end,
        db_path=args.db,
        output_dir=args.output_dir,
        auto_dir=args.auto_dir,
        candidate_types=args.candidate_types,
        gates=gates,
        bounds_config_path=args.bounds_config,
        n_workers=max(1, args.workers),
        universe_categories=universe_cats,
    )

    # ── Banner (NO key, NO prompts) ─────────────────────────────────────────
    print("=" * 80)
    print(" Closed-Loop Strategy Optimizer (Claude API in loop)")
    print(f" target={args.target}  max_iter={args.max_iterations}  "
          f"trials/iter={args.trials_per_iter}")
    print(f" model={model}  temperature={args.temperature}  "
          f"dry_run={args.dry_run}")
    print(f" stop_on_success={stop_on_success}  "
          f"stagnation_iters={args.stagnation_iters}  "
          f"rollback={rollback_on_regression}")
    print(f" workers={loop_config.n_workers}  "
          f"universe_cats={universe_cats or 'full_ai_tech'}")
    print(f" auto_dir={args.auto_dir}")
    print("=" * 80)

    # ── Run ──────────────────────────────────────────────────────────────────
    try:
        global_best, history = run_closed_loop(
            loop_config=loop_config,
            advisor=advisor,
            initial_search_space=initial_space,
        )
    except KeyboardInterrupt:
        print("\n[INTERRUPT] user aborted — partial artifacts preserved.")
        return 130

    # ── Final report ─────────────────────────────────────────────────────────
    print()
    print("=" * 80)
    print(" Closed-Loop Final Report")
    print("=" * 80)
    print(f" iterations_run:      {len(history)}")
    if global_best:
        print(f" global_best_iter:    #{global_best.get('iter_num')}")
        print(f" global_best_obj:     {global_best.get('best_obj', 0):.2f}")
        print(f" val_cat3_gates:      {global_best.get('cat3_gates', 0)}/4")
        print(f" val_n / wr / pf:     "
              f"{global_best.get('val_n', 0)} / "
              f"{global_best.get('val_wr', 0):.2%} / "
              f"{global_best.get('val_pf', 0):.2f}")
        print(f" val_dd:              {global_best.get('val_dd', 0)*100:.2f}%")
        print(f" overfit_warning:     {global_best.get('overfit_warning', False)}")
        print(f" best_summary_path:   {global_best.get('best_summary_path')}")
    else:
        print(" global_best:         (none — no successful iteration)")
    print(f" auto_dir:            {args.auto_dir}")
    print("=" * 80)
    return 0 if global_best else 1


if __name__ == "__main__":
    sys.exit(main())
