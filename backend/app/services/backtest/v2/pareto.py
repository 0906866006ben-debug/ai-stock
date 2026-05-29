"""Pareto front helpers for optimization v2."""
from __future__ import annotations

from typing import Any, Iterable


DEFAULT_OBJECTIVES = ["net_return_pct", "n_trades", "win_rate"]
DEFAULT_MINIMIZE = ["max_drawdown"]


def is_dominated(
    candidate: Any,
    challenger: Any,
    *,
    objectives: Iterable[str] | None = None,
    minimize: Iterable[str] | None = None,
) -> bool:
    """Return True when `challenger` Pareto-dominates `candidate`."""
    objectives = list(objectives or DEFAULT_OBJECTIVES)
    minimize_set = set(minimize or DEFAULT_MINIMIZE)
    for objective in minimize_set:
        if objective not in objectives:
            objectives.append(objective)

    all_at_least_equal = True
    strictly_better = False
    for objective in objectives:
        cand_value = _metric_value(candidate, objective)
        chall_value = _metric_value(challenger, objective)
        if objective in minimize_set:
            cand_value = _minimize_value(objective, cand_value)
            chall_value = _minimize_value(objective, chall_value)
            if chall_value > cand_value:
                all_at_least_equal = False
                break
            if chall_value < cand_value:
                strictly_better = True
        else:
            if chall_value < cand_value:
                all_at_least_equal = False
                break
            if chall_value > cand_value:
                strictly_better = True
    return all_at_least_equal and strictly_better


def pareto_front(
    trials: list[Any],
    objectives: list[str] | None = None,
    minimize: list[str] | None = None,
) -> list[Any]:
    """Return non-dominated trials, preserving input order."""
    objectives = objectives or DEFAULT_OBJECTIVES
    minimize = minimize or DEFAULT_MINIMIZE
    front: list[Any] = []
    for idx, trial in enumerate(trials):
        dominated = any(
            idx != other_idx and is_dominated(trial, other, objectives=objectives, minimize=minimize)
            for other_idx, other in enumerate(trials)
        )
        if not dominated:
            front.append(trial)
    return front


def _metric_value(item: Any, name: str) -> float:
    for source in (
        _attr_path(item, ("objective", "components")),
        _attr_path(item, ("components",)),
        _attr_path(item, ("metrics",)),
        _attr_path(item, ("validation",)),
        _attr_path(item, ("test",)),
        item,
    ):
        if source is None:
            continue
        if isinstance(source, dict) and name in source:
            return _float(source[name])
        if not isinstance(source, dict) and hasattr(source, name):
            return _float(getattr(source, name))
    if name == "net_return":
        return _metric_value(item, "net_return_pct")
    if name == "avg_return_pct":
        return _metric_value(item, "avg_return")
    return 0.0


def _minimize_value(name: str, value: float) -> float:
    if name in {"max_drawdown", "drawdown", "max_dd"}:
        return abs(value)
    return value


def _attr_path(obj: Any, path: tuple[str, ...]) -> Any:
    current = obj
    for part in path:
        if isinstance(current, dict):
            current = current.get(part)
        else:
            current = getattr(current, part, None)
        if current is None:
            return None
    return current


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
