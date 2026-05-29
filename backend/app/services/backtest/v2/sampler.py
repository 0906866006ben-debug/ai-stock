"""Sampling strategies for optimization v2."""
from __future__ import annotations

import hashlib
import json
import logging
import math
import random
from itertools import product
from typing import Any, Iterable, Protocol

logger = logging.getLogger(__name__)

try:  # pragma: no cover - depends on optional local environment
    import optuna

    OPTUNA_AVAILABLE = True
except ImportError:  # pragma: no cover - default in most test environments
    optuna = None  # type: ignore[assignment]
    OPTUNA_AVAILABLE = False


class Sampler(Protocol):
    def sample(self, n: int) -> list[dict[str, Any]]: ...
    def update(self, params: dict[str, Any], result: Any) -> None: ...
    def reset(self) -> None: ...


def params_hash(params: dict[str, Any]) -> str:
    blob = json.dumps(params, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


def estimate_grid_size(search_space: dict[str, list[Any]]) -> int:
    size = 1
    for values in search_space.values():
        size *= len(values)
    return size


def grid_iterator(search_space: dict[str, list[Any]]) -> Iterable[dict[str, Any]]:
    keys = list(search_space.keys())
    for combo in product(*[search_space[key] for key in keys]):
        yield dict(zip(keys, combo))


def sample_params_random(search_space: dict[str, list[Any]], rng: random.Random) -> dict[str, Any]:
    return {key: rng.choice(values) for key, values in search_space.items()}


def sample_params_weighted(
    search_space: dict[str, list[Any]],
    rng: random.Random,
    value_weights: dict[str, dict[Any, float]] | None,
    *,
    exploration_prob: float,
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    for key, values in search_space.items():
        weights_by_value = (value_weights or {}).get(key)
        if not weights_by_value or rng.random() < exploration_prob:
            params[key] = rng.choice(values)
            continue
        weights = [max(float(weights_by_value.get(value, 0.0)), 0.0) for value in values]
        if sum(weights) <= 0:
            params[key] = rng.choice(values)
        else:
            params[key] = rng.choices(values, weights=weights, k=1)[0]
    return params


def sample_unique_params(
    search_space: dict[str, list[Any]],
    rng: random.Random,
    count: int,
    *,
    seen_hashes: set[str] | None = None,
    value_weights: dict[str, dict[Any, float]] | None = None,
    exploration_prob: float = 0.20,
    max_attempts_per_param: int = 500,
) -> list[dict[str, Any]]:
    if count <= 0:
        return []
    seen = seen_hashes if seen_hashes is not None else set()
    grid_size = estimate_grid_size(search_space)
    if len(seen) >= grid_size:
        return []

    if grid_size <= 5000 and grid_size - len(seen) <= count:
        remaining = [params for params in grid_iterator(search_space) if params_hash(params) not in seen]
        rng.shuffle(remaining)
        selected = remaining[:count]
        seen.update(params_hash(params) for params in selected)
        return selected

    selected: list[dict[str, Any]] = []
    for _ in range(min(count, grid_size - len(seen))):
        picked: dict[str, Any] | None = None
        for _attempt in range(max_attempts_per_param):
            params = (
                sample_params_weighted(search_space, rng, value_weights, exploration_prob=exploration_prob)
                if value_weights
                else sample_params_random(search_space, rng)
            )
            p_hash = params_hash(params)
            if p_hash not in seen:
                picked = params
                seen.add(p_hash)
                break

        if picked is None and grid_size <= 5000:
            for params in grid_iterator(search_space):
                p_hash = params_hash(params)
                if p_hash not in seen:
                    picked = params
                    seen.add(p_hash)
                    break
        if picked is None:
            break
        selected.append(picked)
    return selected


class RandomSampler:
    """Uniform random sampler with duplicate avoidance."""

    def __init__(self, search_space: dict[str, list[Any]], *, seed: int | None = None) -> None:
        self.search_space = _validate_search_space(search_space)
        self.rng = random.Random(seed)
        self.seen_hashes: set[str] = set()
        self.history: list[tuple[dict[str, Any], Any]] = []

    def sample(self, n: int) -> list[dict[str, Any]]:
        return sample_unique_params(self.search_space, self.rng, n, seen_hashes=self.seen_hashes)

    def update(self, params: dict[str, Any], result: Any) -> None:
        self.seen_hashes.add(params_hash(params))
        self.history.append((dict(params), result))

    def reset(self) -> None:
        self.seen_hashes.clear()
        self.history.clear()


class AdaptiveSampler(RandomSampler):
    """Lightweight TPE-style categorical sampler."""

    def __init__(
        self,
        search_space: dict[str, list[Any]],
        *,
        seed: int | None = None,
        exploration_prob: float = 0.20,
        elite_fraction: float = 0.35,
        min_elites: int = 3,
        prior_weight: float = 1.0,
    ) -> None:
        super().__init__(search_space, seed=seed)
        self.exploration_prob = exploration_prob
        self.elite_fraction = elite_fraction
        self.min_elites = min_elites
        self.prior_weight = prior_weight

    def sample(self, n: int) -> list[dict[str, Any]]:
        weights = self.build_value_weights()
        return sample_unique_params(
            self.search_space,
            self.rng,
            n,
            seen_hashes=self.seen_hashes,
            value_weights=weights,
            exploration_prob=self.exploration_prob,
        )

    def build_value_weights(self) -> dict[str, dict[Any, float]]:
        weights: dict[str, dict[Any, float]] = {
            key: {value: float(self.prior_weight) for value in values}
            for key, values in self.search_space.items()
        }
        if not self.history:
            return weights

        stable = [
            (params, result)
            for params, result in self.history
            if _n_trades(result) >= 3 and _score(result) > -1999.0 and not _overfit(result)
        ]
        usable = stable or [
            (params, result)
            for params, result in self.history
            if _n_trades(result) >= 3 and _score(result) > -1999.0
        ]
        ranked = sorted(usable or self.history, key=lambda item: _score(item[1]), reverse=True)
        if not ranked:
            return weights

        elite_count = max(self.min_elites, int(math.ceil(len(ranked) * self.elite_fraction)))
        elite_count = min(elite_count, len(ranked))
        for rank, (params, _result) in enumerate(ranked[:elite_count]):
            credit = float(elite_count - rank)
            for key, value in params.items():
                if key in weights and value in weights[key]:
                    weights[key][value] += credit
        return weights


class OptunaSampler:
    """Optuna TPE sampler over categorical search spaces."""

    def __init__(self, search_space: dict[str, list[Any]], *, seed: int | None = None) -> None:
        if not OPTUNA_AVAILABLE:
            raise RuntimeError("optuna is not installed")
        self.search_space = _validate_search_space(search_space)
        self.rng = random.Random(seed)
        sampler = optuna.samplers.TPESampler(seed=seed)  # type: ignore[union-attr]
        self.study = optuna.create_study(direction="maximize", sampler=sampler)  # type: ignore[union-attr]
        self.pending: dict[str, Any] = {}
        self.seen_hashes: set[str] = set()
        self.history: list[tuple[dict[str, Any], Any]] = []

    def sample(self, n: int) -> list[dict[str, Any]]:
        selected: list[dict[str, Any]] = []
        grid_size = estimate_grid_size(self.search_space)
        for _ in range(min(n, grid_size - len(self.seen_hashes))):
            picked: dict[str, Any] | None = None
            picked_trial = None
            for _attempt in range(200):
                trial = self.study.ask()
                params = {key: trial.suggest_categorical(key, values) for key, values in self.search_space.items()}
                p_hash = params_hash(params)
                if p_hash not in self.seen_hashes:
                    picked = params
                    picked_trial = trial
                    self.seen_hashes.add(p_hash)
                    self.pending[p_hash] = trial
                    break
                self.study.tell(trial, -10_000.0)
            if picked is None:
                fallback = sample_unique_params(self.search_space, self.rng, 1, seen_hashes=self.seen_hashes)
                if not fallback:
                    break
                picked = fallback[0]
                picked_trial = None
            selected.append(picked)
            if picked_trial is None:
                self.pending.setdefault(params_hash(picked), None)
        return selected

    def update(self, params: dict[str, Any], result: Any) -> None:
        p_hash = params_hash(params)
        trial = self.pending.pop(p_hash, None)
        if trial is not None:
            self.study.tell(trial, _score(result))
        self.seen_hashes.add(p_hash)
        self.history.append((dict(params), result))

    def reset(self) -> None:
        seed = self.rng.randrange(1_000_000_000)
        sampler = optuna.samplers.TPESampler(seed=seed)  # type: ignore[union-attr]
        self.study = optuna.create_study(direction="maximize", sampler=sampler)  # type: ignore[union-attr]
        self.pending.clear()
        self.seen_hashes.clear()
        self.history.clear()


def build_sampler(
    method: str = "adaptive",
    search_space: dict[str, list[Any]] | None = None,
    *,
    seed: int | None = None,
) -> Sampler:
    if search_space is None:
        raise ValueError("search_space is required")
    normalized = method.lower().strip()
    if normalized == "random":
        return RandomSampler(search_space, seed=seed)
    if normalized == "adaptive":
        return AdaptiveSampler(search_space, seed=seed)
    if normalized == "optuna":
        if not OPTUNA_AVAILABLE:
            logger.warning("optuna not installed; falling back to adaptive sampler")
            return AdaptiveSampler(search_space, seed=seed)
        return OptunaSampler(search_space, seed=seed)
    raise ValueError(f"unknown sampler method: {method}")


def _validate_search_space(search_space: dict[str, list[Any]]) -> dict[str, list[Any]]:
    if not search_space:
        raise ValueError("search_space must not be empty")
    normalized: dict[str, list[Any]] = {}
    for key, values in search_space.items():
        if not values:
            raise ValueError(f"search_space dimension {key!r} has no values")
        normalized[str(key)] = list(values)
    return normalized


def _score(result: Any) -> float:
    for path in (
        ("objective", "primary"),
        ("objective_score",),
        ("score",),
        ("primary",),
    ):
        value = _attr_path(result, path)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                pass
    if isinstance(result, dict):
        for key in ("objective_score", "score", "primary"):
            if key in result:
                return float(result[key])
    return 0.0


def _n_trades(result: Any) -> int:
    for path in (
        ("validation", "n_trades"),
        ("test", "n_trades"),
        ("metrics", "n_trades"),
        ("n_trades",),
    ):
        value = _attr_path(result, path)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                pass
    if isinstance(result, dict):
        for key in ("n_trades", "test_n_trades", "validation_n_trades"):
            if key in result:
                return int(result[key])
    return 0


def _overfit(result: Any) -> bool:
    value = _attr_path(result, ("overfit_warning",))
    if value is None:
        value = _attr_path(result, ("overfit",))
    if isinstance(result, dict):
        value = result.get("overfit_warning", result.get("overfit", value))
    return bool(value)


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

