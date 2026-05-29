"""Main orchestration loop for optimization v2."""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

import yaml

from backend.app.services.backtest.historical_data_store import HistoricalDataStore
from backend.app.services.backtest.trade_simulator import TradeRules
from backend.app.services.backtest.v2.config import LoopConfigV2
from backend.app.services.backtest.v2.evaluator import TrialMetrics, evaluate
from backend.app.services.backtest.v2.objective import ObjectiveScore, compute_objective
from backend.app.services.backtest.v2.pareto import pareto_front
from backend.app.services.backtest.v2.persistence import save_csv, save_json, save_yaml
from backend.app.services.backtest.v2.sampler import Sampler, build_sampler, params_hash
from backend.app.services.backtest.v2.tier_classifier import parse_entry_tier
from backend.app.services.backtest.v2.walk_forward import Split, make_walk_forward_splits
from backend.app.services.sector_service import list_ai_tech_codes, list_categories, list_codes_by_category

logger = logging.getLogger(__name__)


EvaluatorFn = Callable[..., dict[str, TrialMetrics]]


@dataclass
class TrialResultV2:
    trial_id: int
    iteration: int
    params_hash: str
    params: dict[str, Any]
    metrics_by_split: dict[str, TrialMetrics]
    train_metrics: dict[str, TrialMetrics]
    test_metrics: dict[str, TrialMetrics]
    objective: ObjectiveScore
    success: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "trial_id": self.trial_id,
            "iteration": self.iteration,
            "params_hash": self.params_hash,
            "params": self.params,
            "metrics_by_split": {key: value.to_dict() for key, value in self.metrics_by_split.items()},
            "train_metrics": {key: value.to_dict() for key, value in self.train_metrics.items()},
            "test_metrics": {key: value.to_dict() for key, value in self.test_metrics.items()},
            "objective": self.objective.to_dict(),
            "success": self.success,
        }


@dataclass
class OptimizationResultV2:
    config: LoopConfigV2
    splits: list[Split]
    trials: list[TrialResultV2]
    pareto_trials: list[TrialResultV2]
    best_trial: TrialResultV2 | None
    output_dir: Path

    def to_dict(self) -> dict[str, Any]:
        return {
            "config": self.config.to_dict(),
            "splits": [asdict(split) for split in self.splits],
            "trials": [trial.to_dict() for trial in self.trials],
            "pareto_trials": [trial.to_dict() for trial in self.pareto_trials],
            "best_trial": self.best_trial.to_dict() if self.best_trial else None,
            "output_dir": str(self.output_dir),
        }


def run_optimization_v2(
    config: LoopConfigV2,
    *,
    sampler: Sampler | None = None,
    advisor: Any | None = None,
    evaluator_fn: EvaluatorFn = evaluate,
) -> OptimizationResultV2:
    output_dir = Path(config.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    save_yaml(output_dir / "config.yaml", config.to_dict())

    search_space = load_search_space(config.search_space_path)
    sampler = sampler or build_sampler(config.sampler_method, search_space, seed=config.seed)
    splits = make_walk_forward_splits(
        config.start_date,
        config.end_date,
        n_windows=config.walk_forward_windows,
        train_ratio=config.train_ratio,
    )
    universe = resolve_universe(config)
    data_store = HistoricalDataStore(config.db_path)
    base_trade_rules = _base_trade_rules(config)

    trials: list[TrialResultV2] = []
    next_trial_id = 1
    for iteration in range(1, config.max_iterations + 1):
        params_batch = sampler.sample(config.trials_per_iter)
        if not params_batch:
            logger.info("sampler exhausted search space at iteration %s", iteration)
            break
        for params in params_batch:
            params = dict(params)
            params.setdefault("trade_rules.min_entry_tier", config.min_entry_tier)
            metrics_by_split = evaluator_fn(
                params,
                splits,
                universe=universe,
                data_store=data_store,
                rules=base_trade_rules,
                db_path=config.db_path,
                candidate_types=config.candidate_types,
                run_id_prefix=f"v2_{next_trial_id:05d}",
            )
            train_metrics = {name: metric for name, metric in metrics_by_split.items() if not _split_by_name(splits, name).is_test}
            test_metrics = {name: metric for name, metric in metrics_by_split.items() if _split_by_name(splits, name).is_test}
            objective = compute_objective(train_metrics, test_metrics)
            result = TrialResultV2(
                trial_id=next_trial_id,
                iteration=iteration,
                params_hash=params_hash(params),
                params=params,
                metrics_by_split=metrics_by_split,
                train_metrics=train_metrics,
                test_metrics=test_metrics,
                objective=objective,
                success=_passes_success_floor(objective),
            )
            trials.append(result)
            sampler.update(params, result)
            next_trial_id += 1

        if advisor is not None:
            _invoke_advisor(advisor, search_space, trials)

    pareto_trials = pareto_front(trials)
    best_trial = max(trials, key=lambda trial: trial.objective.primary, default=None)
    result = OptimizationResultV2(
        config=config,
        splits=splits,
        trials=trials,
        pareto_trials=pareto_trials,
        best_trial=best_trial,
        output_dir=output_dir,
    )
    _persist_result(result)
    return result


def load_search_space(path: str | Path) -> dict[str, list[Any]]:
    with Path(path).open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    space = data.get("search_space", data)
    if not isinstance(space, dict) or not space:
        raise ValueError(f"Invalid or empty search_space in {path}")
    return {str(key): list(values) for key, values in space.items()}


def resolve_universe(config: LoopConfigV2) -> list[str]:
    if config.universe:
        return sorted({str(code) for code in config.universe})
    categories = list(config.universe_categories)
    if not categories and config.target.lower() not in {"all", "all-categories"}:
        categories = [config.target]
    if not categories:
        return sorted(list_ai_tech_codes())

    resolved: set[str] = set()
    for category in categories:
        category_key = _normalize_category_key(category)
        resolved.update(list_codes_by_category(category_key))
    return sorted(resolved)


def _normalize_category_key(category: str) -> str:
    category = category.strip()
    categories = list_categories()
    if category in categories:
        return category
    compact = category.lower().replace("-", "_")
    if compact.startswith("cat") and compact[3:].isdigit():
        prefix = f"cat_{int(compact[3:])}_"
        for key in categories:
            if key.startswith(prefix):
                return key
    if compact.startswith("cat_") and compact[4:].isdigit():
        prefix = f"cat_{int(compact[4:])}_"
        for key in categories:
            if key.startswith(prefix):
                return key
    return category


def _base_trade_rules(config: LoopConfigV2) -> TradeRules:
    kwargs: dict[str, Any] = {
        "min_entry_tier": int(parse_entry_tier(config.min_entry_tier)),
        "tier_position_multipliers": {1: 0.3, 2: 0.7, 3: 1.0, 4: 1.5},
    }
    if "include_tw_price_limit" in TradeRules.__dataclass_fields__:
        kwargs["include_tw_price_limit"] = bool(config.include_tw_price_limit)
    return TradeRules(**kwargs)


def _split_by_name(splits: list[Split], name: str) -> Split:
    for split in splits:
        if split.name == name:
            return split
    raise KeyError(name)


def _passes_success_floor(objective: ObjectiveScore) -> bool:
    return (
        objective.components.get("n_trades", 0) >= 10
        and objective.components.get("win_rate", 0) >= 0.45
        and objective.components.get("net_return_pct", 0) > 0
    )


def _invoke_advisor(advisor: Any, search_space: dict[str, list[Any]], trials: list[TrialResultV2]) -> None:
    if callable(advisor):
        advisor(search_space, trials)
    elif hasattr(advisor, "advise"):
        advisor.advise(search_space, trials)


def _persist_result(result: OptimizationResultV2) -> None:
    output_dir = result.output_dir
    trial_rows = [_summary_row(trial) for trial in result.trials]
    save_csv(output_dir / "all_iterations_summary.csv", trial_rows)
    save_csv(output_dir / "pareto_front.csv", [_summary_row(trial) for trial in result.pareto_trials])
    save_yaml(output_dir / "best_by_objective.yaml", _best_by_objective(result.trials))
    save_json(output_dir / "global_best.json", result.best_trial.to_dict() if result.best_trial else None)
    save_json(output_dir / "all_trials.json", [trial.to_dict() for trial in result.trials])


def _summary_row(trial: TrialResultV2) -> dict[str, Any]:
    components = trial.objective.components
    return {
        "trial_id": trial.trial_id,
        "iteration": trial.iteration,
        "params_hash": trial.params_hash,
        "primary": round(trial.objective.primary, 6),
        "n_trades": components.get("n_trades", 0),
        "win_rate": components.get("win_rate", 0),
        "net_return_pct": components.get("net_return_pct", 0),
        "avg_return_pct": components.get("avg_return_pct", 0),
        "profit_factor": components.get("profit_factor", 0),
        "max_drawdown": components.get("max_drawdown", 0),
        "wfe": components.get("wfe", 0),
        "success": trial.success,
    }


def _best_by_objective(trials: list[TrialResultV2]) -> dict[str, Any]:
    if not trials:
        return {}
    return {
        "primary": _brief(max(trials, key=lambda trial: trial.objective.primary)),
        "net_return_pct": _brief(max(trials, key=lambda trial: trial.objective.components.get("net_return_pct", 0))),
        "n_trades": _brief(max(trials, key=lambda trial: trial.objective.components.get("n_trades", 0))),
        "win_rate": _brief(max(trials, key=lambda trial: trial.objective.components.get("win_rate", 0))),
        "max_drawdown": _brief(min(trials, key=lambda trial: abs(trial.objective.components.get("max_drawdown", 0)))),
    }


def _brief(trial: TrialResultV2) -> dict[str, Any]:
    return {
        "trial_id": trial.trial_id,
        "params_hash": trial.params_hash,
        "primary": trial.objective.primary,
        "components": trial.objective.components,
        "params": trial.params,
    }

