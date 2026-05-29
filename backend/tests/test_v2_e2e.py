import yaml

from backend.app.services.backtest.v2.config import LoopConfigV2
from backend.app.services.backtest.v2.evaluator import TrialMetrics
from backend.app.services.backtest.v2.loop import load_search_space, resolve_universe, run_optimization_v2


def _fake_evaluator(params, splits, **_kwargs):
    strength = float(params["strength"])
    metrics = {}
    for split in splits:
        test_bonus = 0.5 if split.is_test else 1.0
        metrics[split.name] = TrialMetrics(
            n_trades=int(10 + strength),
            win_rate=0.45 + strength * 0.02 * test_bonus,
            avg_return_pct=0.01 + strength * 0.002 * test_bonus,
            profit_factor=1.1 + strength * 0.1 * test_bonus,
            max_drawdown=-0.08,
            sharpe=0.5 + strength * 0.1,
            expectancy=0.01,
            net_return_pct=0.1 + strength * 0.03 * test_bonus,
            tier_distribution={1: 3, 2: 7},
        )
    return metrics


def test_load_search_space_accepts_yaml(tmp_path):
    path = tmp_path / "space.yaml"
    path.write_text(yaml.safe_dump({"search_space": {"a": [1, 2]}}), encoding="utf-8")
    assert load_search_space(path) == {"a": [1, 2]}


def test_resolve_universe_target_all_is_not_cat3_only():
    universe = resolve_universe(LoopConfigV2(target="all"))
    cat3 = resolve_universe(LoopConfigV2(target="cat3"))
    assert len(universe) > len(cat3) > 0


def test_run_optimization_v2_smoke_writes_artifacts(tmp_path):
    search_space = tmp_path / "space.yaml"
    search_space.write_text(yaml.safe_dump({"search_space": {"strength": [1, 2, 3]}}), encoding="utf-8")
    config = LoopConfigV2(
        target="all",
        max_iterations=1,
        trials_per_iter=3,
        walk_forward_windows=2,
        start_date="2022-01-01",
        end_date="2022-04-30",
        output_dir=tmp_path / "out",
        search_space_path=search_space,
        universe=["2330", "3711"],
        sampler_method="random",
        seed=3,
    )
    result = run_optimization_v2(config, evaluator_fn=_fake_evaluator)
    assert len(result.trials) == 3
    assert result.best_trial is not None
    assert (tmp_path / "out" / "global_best.json").exists()
    assert (tmp_path / "out" / "pareto_front.csv").exists()
    assert (tmp_path / "out" / "all_iterations_summary.csv").exists()

