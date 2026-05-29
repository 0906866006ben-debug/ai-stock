"""Composite objective and walk-forward efficiency for v2."""
from __future__ import annotations

import math
import statistics
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Mapping

from backend.app.services.backtest.v2.evaluator import TrialMetrics


MIN_TRADES_FOR_UNBOUNDED_PF = 10


@dataclass
class WalkForwardEfficiency:
    train_score: float
    test_score: float
    ratio: float

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


@dataclass
class ObjectiveScore:
    primary: float
    components: dict[str, float] = field(default_factory=dict)
    overfit_penalty: float = 0.0
    sample_penalty: float = 0.0
    stability_penalty: float = 0.0
    wfe: WalkForwardEfficiency | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.wfe:
            data["wfe"] = self.wfe.to_dict()
        return data


def compute_objective(
    train_metrics: TrialMetrics | Mapping[str, TrialMetrics] | Iterable[TrialMetrics],
    test_metrics: TrialMetrics | Mapping[str, TrialMetrics] | Iterable[TrialMetrics],
    *,
    weights: Mapping[str, float] | None = None,
    min_trades: int = 10,
) -> ObjectiveScore:
    """Compute a scalar score plus raw components for Pareto ranking."""
    train_agg = aggregate_metrics(_coerce_metrics(train_metrics))
    test_items = _coerce_metrics(test_metrics)
    test_agg = aggregate_metrics(test_items)

    train_score = _split_score(train_agg, weights)
    test_score = _split_score(test_agg, weights)
    wfe = _walk_forward_efficiency(train_score, test_score)

    sample_penalty = _sample_penalty(test_agg.n_trades, min_trades)
    overfit_penalty = _overfit_penalty(train_agg, test_agg, train_score, test_score)
    split_scores = [_split_score(metric, weights) for metric in test_items]
    stability_penalty = statistics.pstdev(split_scores) * 0.25 if len(split_scores) > 1 else 0.0

    primary = test_score - sample_penalty - overfit_penalty - stability_penalty
    if wfe.ratio > 0:
        primary += min(wfe.ratio, 1.5) * 10.0

    components = {
        "net_return_pct": test_agg.net_return_pct,
        "n_trades": float(test_agg.n_trades),
        "win_rate": test_agg.win_rate,
        "avg_return_pct": test_agg.avg_return_pct,
        "profit_factor": _finite_or_cap(test_agg.profit_factor),
        "max_drawdown": test_agg.max_drawdown,
        "sharpe": test_agg.sharpe,
        "sortino": test_agg.sortino,
        "expectancy": test_agg.expectancy,
        "wfe": wfe.ratio,
    }
    return ObjectiveScore(
        primary=float(primary),
        components=components,
        overfit_penalty=float(overfit_penalty),
        sample_penalty=float(sample_penalty),
        stability_penalty=float(stability_penalty),
        wfe=wfe,
    )


def aggregate_metrics(metrics: Iterable[TrialMetrics]) -> TrialMetrics:
    items = list(metrics)
    if not items:
        return TrialMetrics()
    n_trades = sum(metric.n_trades for metric in items)
    net_return = sum(metric.net_return_pct for metric in items)
    return TrialMetrics(
        n_trades=n_trades,
        win_rate=_weighted_average(items, "win_rate"),
        avg_return_pct=_weighted_average(items, "avg_return_pct"),
        profit_factor=_mean([_finite_or_cap(metric.profit_factor) for metric in items]),
        max_drawdown=_worst_drawdown(metric.max_drawdown for metric in items),
        sharpe=_mean(metric.sharpe for metric in items),
        sortino=_mean(metric.sortino for metric in items),
        expectancy=_weighted_average(items, "expectancy"),
        net_return_pct=net_return,
        avg_hold_days=_weighted_average(items, "avg_hold_days"),
        tier_distribution=_merge_tier_distributions(items),
    )


def _coerce_metrics(value: TrialMetrics | Mapping[str, TrialMetrics] | Iterable[TrialMetrics]) -> list[TrialMetrics]:
    if isinstance(value, TrialMetrics):
        return [value]
    if isinstance(value, Mapping):
        return list(value.values())
    return list(value)


def _split_score(metric: TrialMetrics, weights: Mapping[str, float] | None) -> float:
    w = {
        "net_return_pct": 300.0,
        "avg_return_pct": 500.0,
        "win_rate": 80.0,
        "profit_factor": 8.0,
        "expectancy": 200.0,
        "n_trades": 1.0,
        "max_drawdown": 120.0,
        "sharpe": 2.0,
    }
    if weights:
        w.update(weights)
    pf = _usable_profit_factor(metric.profit_factor, metric.n_trades)
    return (
        metric.net_return_pct * w["net_return_pct"]
        + metric.avg_return_pct * w["avg_return_pct"]
        + metric.win_rate * w["win_rate"]
        + pf * w["profit_factor"]
        + metric.expectancy * w["expectancy"]
        + metric.n_trades * w["n_trades"]
        + metric.max_drawdown * w["max_drawdown"]
        + metric.sharpe * w["sharpe"]
    )


def _walk_forward_efficiency(train_score: float, test_score: float) -> WalkForwardEfficiency:
    if train_score <= 0 or test_score <= 0:
        ratio = 0.0
    else:
        ratio = min(test_score / train_score, 2.0)
    return WalkForwardEfficiency(train_score=train_score, test_score=test_score, ratio=ratio)


def _sample_penalty(n_trades: int, min_trades: int) -> float:
    if n_trades >= min_trades:
        return 0.0
    missing = min_trades - n_trades
    return float(missing * missing * 2.0)


def _overfit_penalty(train: TrialMetrics, test: TrialMetrics, train_score: float, test_score: float) -> float:
    score_gap = max(0.0, train_score - test_score) * 0.10
    win_rate_gap = max(0.0, train.win_rate - test.win_rate) * 30.0
    return_gap = max(0.0, train.avg_return_pct - test.avg_return_pct) * 200.0
    return score_gap + win_rate_gap + return_gap


def _usable_profit_factor(value: float, n_trades: int) -> float:
    if not math.isfinite(value):
        return 5.0 if n_trades >= MIN_TRADES_FOR_UNBOUNDED_PF else 0.0
    return min(max(value, 0.0), 5.0)


def _finite_or_cap(value: float) -> float:
    if math.isfinite(value):
        return float(value)
    return 999.0


def _weighted_average(items: list[TrialMetrics], attr: str) -> float:
    total_weight = sum(max(metric.n_trades, 0) for metric in items)
    if total_weight <= 0:
        return _mean(getattr(metric, attr) for metric in items)
    return sum(getattr(metric, attr) * max(metric.n_trades, 0) for metric in items) / total_weight


def _mean(values: Iterable[float]) -> float:
    vals = [float(value) for value in values]
    return sum(vals) / len(vals) if vals else 0.0


def _worst_drawdown(values: Iterable[float]) -> float:
    vals = [float(value) for value in values]
    if not vals:
        return 0.0
    negatives = [value for value in vals if value < 0]
    return min(negatives) if negatives else max(vals)


def _merge_tier_distributions(items: list[TrialMetrics]) -> dict[int, int]:
    merged: dict[int, int] = {}
    for metric in items:
        for tier, count in (metric.tier_distribution or {}).items():
            merged[int(tier)] = merged.get(int(tier), 0) + int(count)
    return merged

