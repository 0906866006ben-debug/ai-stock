from types import SimpleNamespace

import pytest

from backend.app.services.backtest.v2 import sampler as sampler_module
from backend.app.services.backtest.v2.sampler import (
    AdaptiveSampler,
    RandomSampler,
    Sampler,
    build_sampler,
    params_hash,
)


def test_random_sampler_covers_all_dims():
    sampler = RandomSampler({"a": [1, 2], "b": ["x", "y"]}, seed=7)
    params = sampler.sample(1)[0]
    assert set(params) == {"a", "b"}
    assert params["a"] in [1, 2]
    assert params["b"] in ["x", "y"]


def test_random_sampler_no_duplicates_in_dense_space():
    sampler = RandomSampler({"a": [1, 2], "b": ["x", "y"]}, seed=1)
    batch = sampler.sample(4)
    assert len(batch) == 4
    assert len({params_hash(params) for params in batch}) == 4
    assert sampler.sample(1) == []


def test_adaptive_sampler_learns_from_elites():
    search_space = {"x": [1, 2], "y": list(range(80))}
    sampler = AdaptiveSampler(search_space, seed=4, exploration_prob=0.0)
    for y in range(8):
        sampler.update({"x": 2, "y": y}, {"objective_score": 100 - y, "n_trades": 20})
    for y in range(8, 20):
        sampler.update({"x": 1, "y": y}, {"objective_score": 1, "n_trades": 20})

    batch = sampler.sample(50)
    assert sum(1 for params in batch if params["x"] == 2) > sum(1 for params in batch if params["x"] == 1)


def test_adaptive_sampler_explore_exploit_balance():
    sampler = AdaptiveSampler({"x": [1, 2], "y": list(range(20))}, seed=5, exploration_prob=0.5)
    sampler.update({"x": 2, "y": 1}, {"objective_score": 99, "n_trades": 20})
    batch = sampler.sample(20)
    assert {params["x"] for params in batch} == {1, 2}


def test_optuna_sampler_falls_back_when_unavailable(monkeypatch):
    monkeypatch.setattr(sampler_module, "OPTUNA_AVAILABLE", False)
    sampler = build_sampler("optuna", {"a": [1, 2]}, seed=1)
    assert isinstance(sampler, AdaptiveSampler)


def test_sampler_protocol_interface():
    sampler: Sampler = build_sampler("random", {"a": [1]}, seed=1)
    assert sampler.sample(1) == [{"a": 1}]
    sampler.update({"a": 1}, SimpleNamespace(objective_score=1, n_trades=3))


def test_sampler_reset_clears_history():
    sampler = RandomSampler({"a": [1, 2]}, seed=1)
    sampler.update({"a": 1}, {"objective_score": 1})
    sampler.reset()
    assert sampler.history == []
    assert sampler.seen_hashes == set()


def test_unique_sampling_avoids_duplicates():
    sampler = RandomSampler({"a": [1, 2], "b": [3]}, seed=2)
    first = sampler.sample(1)[0]
    second = sampler.sample(2)
    assert first not in second
    assert len(second) == 1


def test_unknown_sampler_rejected():
    with pytest.raises(ValueError):
        build_sampler("mystery", {"a": [1]})

