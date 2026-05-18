"""Equivalence tests for the feature cache (#5 vectorize/cache speedup).

Critical invariant: results from `evaluate_surge_candidate` MUST be bit-perfect
identical whether features are pre-computed/cached or freshly computed inside
the function. Any divergence means the cache is unsafe to enable.

Strategy:
  1. Build a deterministic synthetic OHLCV DataFrame (no DB dependency)
  2. Call evaluate_surge_candidate twice:
     - Once with precomputed_features=None (slow path)
     - Once with precomputed_features=<cached features> (fast path)
  3. Compare every field of the returned SurgeCandidateResult byte-for-byte
"""
from __future__ import annotations

from dataclasses import asdict

import numpy as np
import pandas as pd
import pytest

from backend.app.services.screener_rules import load_surge_candidate_rules
from backend.app.services.screener_service import (
    _canonicalize_ohlcv,
    _compute_base_features,
    evaluate_surge_candidate,
)


def _make_synthetic_ohlcv(n_bars: int = 150, seed: int = 42) -> pd.DataFrame:
    """Generate a plausible OHLCV DataFrame for testing.

    Pattern: 100 days of mild uptrend (10-30% range), then 30 days of
    consolidation (volume contraction), then 20 days of breakout setup.
    """
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2024-01-01", periods=n_bars).strftime("%Y-%m-%d").tolist()

    # Random walk close price starting at 100
    returns = rng.normal(loc=0.001, scale=0.015, size=n_bars)
    closes = 100 * np.exp(np.cumsum(returns))
    # Trend phase: mild up
    closes[:100] *= np.linspace(1.0, 1.15, 100)
    # Base phase: tight range
    closes[100:130] = closes[100:130] * np.linspace(1.0, 1.02, 30) * (1 + rng.normal(0, 0.005, 30))
    # Pre-breakout phase: edging up
    closes[130:] *= np.linspace(1.0, 1.05, 20)

    highs = closes * (1 + rng.uniform(0.005, 0.02, n_bars))
    lows = closes * (1 - rng.uniform(0.005, 0.02, n_bars))
    opens = closes + rng.uniform(-0.5, 0.5, n_bars)
    volumes = rng.integers(500_000, 5_000_000, n_bars).astype(int)
    # Volume contraction during base phase
    volumes[100:130] = (volumes[100:130] * 0.6).astype(int)
    turnover = closes * volumes

    return pd.DataFrame({
        "date": dates,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
        "turnover": turnover,
    })


def _make_synthetic_market(n_bars: int = 150, seed: int = 7) -> pd.DataFrame:
    """Synthetic TAIEX-like market index."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2024-01-01", periods=n_bars).strftime("%Y-%m-%d").tolist()
    returns = rng.normal(loc=0.0005, scale=0.01, size=n_bars)
    closes = 17000 * np.exp(np.cumsum(returns))
    return pd.DataFrame({
        "date": dates,
        "open": closes - 5,
        "high": closes + 10,
        "low": closes - 10,
        "close": closes,
        "volume": rng.integers(1, 5, n_bars).astype(int),
        "turnover": closes * 100,
    })


@pytest.fixture
def synthetic_data():
    df = _make_synthetic_ohlcv()
    df_market = _make_synthetic_market()
    df_eval = df.rename(columns={
        "open": "Open", "high": "High", "low": "Low",
        "close": "Close", "volume": "Volume", "turnover": "Turnover",
    })
    return df_eval, df_market


def _result_to_dict(result):
    if result is None:
        return None
    return {
        "stock_id": result.stock_id,
        "candidate_type": result.candidate_type,
        "surge_candidate_score": result.surge_candidate_score,
        "confidence_score": result.confidence_score,
        "risk_score": result.risk_score,
        "scores": asdict(result.scores) if hasattr(result.scores, "__dataclass_fields__") else (
            result.scores.model_dump() if hasattr(result.scores, "model_dump") else dict(result.scores)
        ),
        "metrics": result.metrics.model_dump() if hasattr(result.metrics, "model_dump") else dict(result.metrics),
        "risk_flags": list(result.risk_flags),
        "missing_data": list(result.missing_data),
        "data_quality_flags": sorted(result.data_quality_flags),
    }


def test_cached_features_match_uncached(synthetic_data):
    """Run evaluate twice — with and without precomputed features.

    Every output field must match exactly. If any single field differs, the
    cache is unsafe and we should NOT enable it.
    """
    df_eval, df_market = synthetic_data
    rules = load_surge_candidate_rules()

    # Path A: original (no cache)
    result_uncached = evaluate_surge_candidate(
        stock_id="TEST",
        stock_name="TEST",
        df=df_eval,
        df_market=df_market,
        include_unfit=True,   # don't filter out unfit results — we want comparison
    )

    # Path B: cached (pre-compute features, then pass in)
    normalized, has_turnover = _canonicalize_ohlcv(df_eval)
    if not has_turnover:
        normalized = normalized.copy()
        normalized["turnover_value"] = normalized["close"] * normalized["volume"]
    dqf: list[str] = []
    md: list[str] = []
    features = _compute_base_features(
        normalized, df_market, rules,
        data_quality_flags=dqf, missing_data=md,
        market_index_source="unavailable",
    )

    result_cached = evaluate_surge_candidate(
        stock_id="TEST",
        stock_name="TEST",
        df=df_eval,
        df_market=df_market,
        include_unfit=True,
        precomputed_features=features,
    )

    a = _result_to_dict(result_uncached)
    b = _result_to_dict(result_cached)
    assert a is not None and b is not None, "Both paths should return a result"

    # Compare top-level scalar fields
    for field in ("stock_id", "candidate_type", "surge_candidate_score",
                  "confidence_score", "risk_score"):
        assert a[field] == b[field], f"field '{field}' differs: {a[field]!r} vs {b[field]!r}"

    # Compare risk flags + missing data + quality flags (sets/sorted lists)
    assert sorted(a["risk_flags"]) == sorted(b["risk_flags"]), \
        f"risk_flags differ:\n  uncached={sorted(a['risk_flags'])}\n  cached  ={sorted(b['risk_flags'])}"
    assert sorted(a["missing_data"]) == sorted(b["missing_data"])
    assert a["data_quality_flags"] == b["data_quality_flags"]

    # Compare metrics field-by-field
    for key in a["metrics"]:
        va = a["metrics"][key]
        vb = b["metrics"][key]
        if isinstance(va, float) and isinstance(vb, float):
            assert va == pytest.approx(vb, rel=1e-12, abs=1e-12), \
                f"metric '{key}' differs: {va} vs {vb}"
        else:
            assert va == vb, f"metric '{key}' differs: {va!r} vs {vb!r}"

    # Compare scores
    for key in a["scores"]:
        assert a["scores"][key] == b["scores"][key], \
            f"score '{key}' differs: {a['scores'][key]} vs {b['scores'][key]}"


def test_cached_features_match_uncached_no_market(synthetic_data):
    """Same check but without a market index (forces missing_data path)."""
    df_eval, _ = synthetic_data
    rules = load_surge_candidate_rules()

    result_uncached = evaluate_surge_candidate(
        stock_id="TEST",
        stock_name="TEST",
        df=df_eval,
        df_market=None,
        include_unfit=True,
    )

    normalized, has_turnover = _canonicalize_ohlcv(df_eval)
    if not has_turnover:
        normalized = normalized.copy()
        normalized["turnover_value"] = normalized["close"] * normalized["volume"]
    dqf: list[str] = []
    md: list[str] = []
    features = _compute_base_features(
        normalized, None, rules,
        data_quality_flags=dqf, missing_data=md,
        market_index_source="unavailable",
    )

    result_cached = evaluate_surge_candidate(
        stock_id="TEST",
        stock_name="TEST",
        df=df_eval,
        df_market=None,
        include_unfit=True,
        precomputed_features=features,
    )

    a = _result_to_dict(result_uncached)
    b = _result_to_dict(result_cached)
    assert a is not None and b is not None

    assert a["candidate_type"] == b["candidate_type"]
    assert a["surge_candidate_score"] == b["surge_candidate_score"]
    assert sorted(a["risk_flags"]) == sorted(b["risk_flags"])
    assert sorted(a["missing_data"]) == sorted(b["missing_data"])

    for key in a["metrics"]:
        va = a["metrics"][key]
        vb = b["metrics"][key]
        if isinstance(va, float) and isinstance(vb, float):
            assert va == pytest.approx(vb, rel=1e-12, abs=1e-12), \
                f"metric '{key}' differs: {va} vs {vb}"
        else:
            assert va == vb, f"metric '{key}' differs: {va!r} vs {vb!r}"


def test_compute_base_features_returns_side_effects(synthetic_data):
    """`_compute_base_features` must record what it appended to the flag lists
    in the returned dict, so cached results can replay side-effects."""
    df_eval, _ = synthetic_data
    rules = load_surge_candidate_rules()

    normalized, _ = _canonicalize_ohlcv(df_eval)
    normalized = normalized.copy()
    if "turnover_value" not in normalized.columns:
        normalized["turnover_value"] = normalized["close"] * normalized["volume"]

    dqf: list[str] = []
    md: list[str] = []
    features = _compute_base_features(
        normalized, None, rules,   # None market → forces "market_index" append
        data_quality_flags=dqf, missing_data=md,
        market_index_source="unavailable",
    )

    assert "_data_quality_flags" in features
    assert "_missing_data" in features
    # Without market → missing_data should include market_index
    assert "market_index" in features["_missing_data"]
    assert "market_index" in md
