import math

from backend.app.services.backtest.v2.evaluator import TrialMetrics
from backend.app.services.backtest.v2.objective import aggregate_metrics, compute_objective


def _metrics(**overrides):
    data = {
        "n_trades": 20,
        "win_rate": 0.55,
        "avg_return_pct": 0.03,
        "profit_factor": 1.8,
        "max_drawdown": -0.08,
        "sharpe": 1.2,
        "sortino": 1.8,
        "expectancy": 0.02,
        "net_return_pct": 0.60,
        "avg_hold_days": 10.0,
        "tier_distribution": {2: 10, 3: 10},
    }
    data.update(overrides)
    return TrialMetrics(**data)


def test_compute_objective_positive_for_good_walk_forward():
    score = compute_objective(_metrics(), [_metrics(), _metrics(net_return_pct=0.45)])
    assert score.primary > 0
    assert score.components["n_trades"] == 40


def test_low_sample_penalty_applies():
    score = compute_objective(_metrics(), [_metrics(n_trades=2, net_return_pct=0.05)], min_trades=10)
    assert score.sample_penalty > 0


def test_overfit_penalty_applies_when_train_beats_test_badly():
    score = compute_objective(
        _metrics(win_rate=0.9, avg_return_pct=0.08, net_return_pct=1.6),
        [_metrics(win_rate=0.4, avg_return_pct=-0.01, net_return_pct=-0.1)],
    )
    assert score.overfit_penalty > 0


def test_walk_forward_efficiency_ratio_is_capped():
    score = compute_objective(_metrics(net_return_pct=0.1), [_metrics(net_return_pct=3.0)])
    assert score.wfe is not None
    assert score.wfe.ratio <= 2.0


def test_unbounded_profit_factor_small_sample_not_rewarded():
    score = compute_objective(_metrics(), [_metrics(n_trades=1, profit_factor=math.inf, net_return_pct=0.01)])
    assert score.components["profit_factor"] == 999.0
    assert score.sample_penalty > 0


def test_aggregate_metrics_sums_trades_and_tiers():
    agg = aggregate_metrics([_metrics(tier_distribution={1: 2}), _metrics(tier_distribution={2: 3})])
    assert agg.n_trades == 40
    assert agg.tier_distribution == {1: 2, 2: 3}

