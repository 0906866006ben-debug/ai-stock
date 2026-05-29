from types import SimpleNamespace

from backend.app.services.backtest.v2.pareto import is_dominated, pareto_front


def _trial(name, **components):
    return SimpleNamespace(name=name, objective=SimpleNamespace(components=components))


def test_is_dominated_when_all_objectives_worse_or_equal():
    weak = _trial("weak", net_return_pct=0.05, n_trades=10, win_rate=0.45, max_drawdown=-0.10)
    strong = _trial("strong", net_return_pct=0.08, n_trades=12, win_rate=0.50, max_drawdown=-0.08)
    assert is_dominated(weak, strong)


def test_not_dominated_when_tradeoff_exists():
    low_dd = _trial("low_dd", net_return_pct=0.05, n_trades=10, win_rate=0.45, max_drawdown=-0.03)
    high_ret = _trial("high_ret", net_return_pct=0.08, n_trades=12, win_rate=0.50, max_drawdown=-0.15)
    assert not is_dominated(low_dd, high_ret)
    assert not is_dominated(high_ret, low_dd)


def test_pareto_front_removes_dominated_trials():
    weak = _trial("weak", net_return_pct=0.01, n_trades=3, win_rate=0.40, max_drawdown=-0.20)
    strong = _trial("strong", net_return_pct=0.08, n_trades=20, win_rate=0.55, max_drawdown=-0.08)
    tradeoff = _trial("tradeoff", net_return_pct=0.12, n_trades=5, win_rate=0.80, max_drawdown=-0.12)
    assert [trial.name for trial in pareto_front([weak, strong, tradeoff])] == ["strong", "tradeoff"]


def test_reward_hack_single_trade_is_dominated_by_broader_good_trial():
    hack = _trial("hack", net_return_pct=0.02, n_trades=1, win_rate=1.0, max_drawdown=0.0)
    robust = _trial("robust", net_return_pct=0.04, n_trades=50, win_rate=1.0, max_drawdown=0.0)
    assert is_dominated(hack, robust)


def test_metric_lookup_accepts_dict_trials():
    trials = [
        {"components": {"net_return_pct": 0.01, "n_trades": 2, "win_rate": 0.4, "max_drawdown": 0.2}},
        {"components": {"net_return_pct": 0.02, "n_trades": 3, "win_rate": 0.5, "max_drawdown": 0.1}},
    ]
    assert pareto_front(trials) == [trials[1]]

