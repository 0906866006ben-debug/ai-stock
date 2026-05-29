"""CLI entrypoint for Phase 12 optimization v2."""
from __future__ import annotations

import argparse
import logging

from backend.app.services.backtest.v2.config import LoopConfigV2
from backend.app.services.backtest.v2.loop import run_optimization_v2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run optimization system v2")
    parser.add_argument("--target", default="all")
    parser.add_argument("--max-iterations", type=int, default=1)
    parser.add_argument("--trials-per-iter", type=int, default=20)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--walk-forward-windows", type=int, default=5)
    parser.add_argument("--train-ratio", type=float, default=0.8)
    parser.add_argument("--sampler", choices=["random", "adaptive", "optuna"], default="adaptive")
    parser.add_argument("--min-entry-tier", default="C")
    parser.add_argument("--objective-method", choices=["pareto", "composite"], default="pareto")
    parser.add_argument("--start", dest="start_date", default="2022-11-01")
    parser.add_argument("--end", dest="end_date", default="2026-05-15")
    parser.add_argument("--output-dir", default="artifacts/strategy_optimization_v2")
    parser.add_argument("--db-path", default="backend/historical_data.db")
    parser.add_argument("--search-space", dest="search_space_path", default="backend/app/services/backtest/v1/optimizer_search_space.yaml")
    parser.add_argument("--universe", nargs="*", default=[])
    parser.add_argument("--universe-categories", nargs="*", default=[])
    parser.add_argument("--candidate-types", nargs="*", default=["起漲前觀察"])
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--disable-tw-price-limit", action="store_true")
    parser.add_argument("--log-level", default="INFO")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=getattr(logging, str(args.log_level).upper(), logging.INFO), format="%(levelname)s:%(name)s:%(message)s")
    config = LoopConfigV2(
        target=args.target,
        max_iterations=args.max_iterations,
        trials_per_iter=args.trials_per_iter,
        workers=args.workers,
        walk_forward_windows=args.walk_forward_windows,
        train_ratio=args.train_ratio,
        sampler_method=args.sampler,
        min_entry_tier=args.min_entry_tier,
        objective_method=args.objective_method,
        start_date=args.start_date,
        end_date=args.end_date,
        output_dir=args.output_dir,
        db_path=args.db_path,
        search_space_path=args.search_space_path,
        universe=args.universe,
        universe_categories=args.universe_categories,
        candidate_types=args.candidate_types,
        seed=args.seed,
        include_tw_price_limit=not args.disable_tw_price_limit,
    )
    result = run_optimization_v2(config)
    if result.best_trial is None:
        print(f"No completed v2 trials. Artifacts: {result.output_dir}")
        return 1
    best = result.best_trial
    print(
        f"Best trial #{best.trial_id}: primary={best.objective.primary:.3f}, "
        f"n={best.objective.components.get('n_trades', 0)}, "
        f"WR={best.objective.components.get('win_rate', 0):.1%}. "
        f"Artifacts: {result.output_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

