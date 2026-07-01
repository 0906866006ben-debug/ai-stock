"""Unit tests for the value-factor cohort engine (value_cohort.py).

Covers cross-sectional grouping (F-Score buckets + deciles), the cost/excess arithmetic,
the high−low decision-gate summary, and an end-to-end row build over a synthetic store
(net = gross − round-trip cost; excess = net − TAIEX).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from backend.app.services.backtest.historical_data_store import HistoricalDataStore
from backend.app.services.strategy.canslim.params import load_params
from backend.app.services.strategy.value import value_cohort as vc

PARAMS = load_params()


def _store(tmp_path: Path, symbols=("AAA", "TAIEX"), n=300):
    store = HistoricalDataStore(tmp_path / "ohlcv.db")
    start = pd.Timestamp("2020-01-01")
    rows = []
    for sym in symbols:
        for i in range(n):
            close = 100.0 + i
            rows.append({
                "stock_id": sym, "date": (start + pd.Timedelta(days=i)).strftime("%Y-%m-%d"),
                "open": close, "high": close, "low": close, "close": close,
                "volume": 1_000_000, "turnover": close * 1_000_000,
            })
    store.upsert_rows(rows)
    dates = [(start + pd.Timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n)]
    return store, dates


# ── grouping ──────────────────────────────────────────────────────────────────
def test_assign_groups_fscore_buckets():
    df = pd.DataFrame({
        "as_of_date": ["2020-01-01"] * 4,
        "fscore": [9, 8, 2, 0], "factor_value": [9.0, 8.0, 2.0, 0.0],
    })
    out = vc._assign_groups(df, "fscore")
    assert list(out["group"]) == ["F9", "F8", "F2", "F0"]


def test_decile_labels_assigns_d1_to_d10():
    s = pd.Series(range(20))  # 20 distinct values -> 10 deciles, 2 each
    labels = vc._decile_labels(s)
    assert labels.iloc[0] == "D1"     # lowest
    assert labels.iloc[-1] == "D10"   # highest
    assert set(labels) == {f"D{i}" for i in range(1, 11)}


def test_decile_labels_too_few_returns_none():
    labels = vc._decile_labels(pd.Series([1, 2, 3]))
    assert labels.isna().all()


def test_high_low_masks_fscore_uses_yaml_bands():
    df = pd.DataFrame({"fscore": [9, 8, 5, 2, 0]})
    high, low, label = vc._high_low_masks(df, "fscore", PARAMS)
    assert list(high) == [True, True, False, False, False]   # >= 8
    assert list(low) == [False, False, False, True, True]    # <= 2
    assert "F>=8" in label and "F<=2" in label


# ── summary: cost / excess / high-low spread ────────────────────────────────────
def test_summarize_high_minus_low_and_excess():
    # Two F-score buckets; high (9) returns more than low (1); excess vs TAIEX present.
    df = pd.DataFrame({
        "as_of_date": ["2020-01-01"] * 2, "year": ["2020"] * 2,
        "stock_id": ["HI", "LO"], "fscore": [9, 1], "factor_value": [9.0, 1.0],
        "market_cap": [1e9, 1e9],
        "net_1m": [0.10, -0.02], "net_3m": [0.2, 0.0], "net_6m": [0.3, 0.05], "net_12m": [0.5, 0.1],
        "excess_1m": [0.08, -0.05], "excess_3m": [0.15, -0.05], "excess_6m": [0.2, -0.05], "excess_12m": [0.4, -0.05],
    })
    df = vc._assign_groups(df, "fscore")
    s = vc.summarize_value_cohort(df, "fscore", PARAMS)
    hl = s["high_minus_low"]["12m"]
    assert hl["high"]["mean"] == 0.5 and hl["low"]["mean"] == 0.1
    assert abs(hl["spread_net"] - 0.4) < 1e-9             # 0.5 - 0.1
    assert hl["high_excess_vs_taiex"] == 0.4
    assert s["by_year_high_minus_low"]["2020"]["spread_net_12m"] == 0.4


# ── end-to-end rows over a synthetic store ──────────────────────────────────────
def test_value_cohort_rows_net_and_excess(tmp_path: Path, monkeypatch):
    store, dates = _store(tmp_path)
    as_of = dates[100]  # entry close 200; +20 bar -> 220 -> gross_1m = 0.10 for AAA and TAIEX

    monkeypatch.setattr(vc, "get_universe_as_of", lambda *a, **k: ["AAA"])
    monkeypatch.setattr(
        vc, "_factor_for_symbol",
        lambda *a, **k: {"market_cap": 1e9, "factor_value": 7.0, "fscore": 7},
    )

    df = vc._value_cohort_rows(store, None, PARAMS, ["AAA"], [as_of], "fscore")
    assert len(df) == 1
    row = df.iloc[0]
    gross_1m = 220.0 / 200.0 - 1.0
    assert abs(row["gross_1m"] - gross_1m) < 1e-6
    # net = gross - round-trip cost
    assert abs(row["net_1m"] - (gross_1m - vc.COST_ROUNDTRIP)) < 1e-6
    # AAA and TAIEX move identically here, so excess = net - taiex = -cost
    assert abs(row["excess_1m"] - (-vc.COST_ROUNDTRIP)) < 1e-6
    assert row["group"] == "F7"


def test_value_cohort_rows_forwards_max_staleness(tmp_path: Path, monkeypatch):
    """Survivorship correction must reach get_universe_as_of."""
    store, dates = _store(tmp_path)
    captured: dict = {}

    def fake_universe(as_of, data_store, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(vc, "get_universe_as_of", fake_universe)
    vc._value_cohort_rows(store, None, PARAMS, ["AAA"], [dates[100]], "fscore", max_staleness_days=10)
    assert captured.get("max_staleness_days") == 10
