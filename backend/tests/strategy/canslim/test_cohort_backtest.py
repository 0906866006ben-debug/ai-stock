from __future__ import annotations

from pathlib import Path

import pandas as pd

from backend.app.models.screener_schemas import ScreeningResult
from backend.app.services.backtest.historical_data_store import HistoricalDataStore
from backend.app.services.strategy.canslim import cohort_backtest as cb
from backend.app.services.strategy.canslim.params import load_params
from backend.app.services.strategy.canslim.types import MarketFeatures


def _store(tmp_path: Path, symbols=("AAA", "TAIEX"), n=300) -> HistoricalDataStore:
    store = HistoricalDataStore(tmp_path / "ohlcv.db")
    start = pd.Timestamp("2020-01-01")
    rows = []
    for sym in symbols:
        for i in range(n):
            close = 100.0 + i  # linear so forward returns are predictable
            rows.append({
                "stock_id": sym, "date": (start + pd.Timedelta(days=i)).strftime("%Y-%m-%d"),
                "open": close, "high": close, "low": close, "close": close,
                "volume": 1_000_000, "turnover": close * 1_000_000,
            })
    store.upsert_rows(rows)
    return store, [(start + pd.Timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n)]


def test_forward_returns_basic_and_pit_safe(tmp_path: Path):
    store, dates = _store(tmp_path)
    as_of = dates[100]            # entry close = 200
    fwd = cb.forward_returns_for(store, "AAA", as_of)
    assert fwd is not None
    # +20 forward bar close = 220 -> 220/200 - 1 = 0.10
    assert abs(fwd["fwd_1m"] - (220.0 / 200.0 - 1.0)) < 1e-6
    assert abs(fwd["fwd_3m"] - (260.0 / 200.0 - 1.0)) < 1e-6
    # 12m needs 252 forward bars; only ~199 exist after index 100 -> None
    assert fwd["fwd_12m"] is None
    # max run-up over the forward window is positive (price rises); dd ~0 (monotonic up)
    assert fwd["max_runup_12m"] > 0


def test_forward_returns_none_when_no_entry_bar(tmp_path: Path):
    store, _ = _store(tmp_path)
    assert cb.forward_returns_for(store, "AAA", "2010-01-01") is None  # before any data


def test_bucket_metrics():
    df = pd.DataFrame({"fwd_1m": [0.3, 0.1, -0.2, 0.6, None]})
    m = cb._bucket_metrics(df, "fwd_1m")
    assert m["n"] == 4
    assert abs(m["mean"] - 0.2) < 1e-9
    assert abs(m["median"] - 0.2) < 1e-9
    assert m["pct_pos"] == 0.75
    assert m["pct_gt20"] == 0.5    # 0.3 and 0.6
    assert m["pct_gt50"] == 0.25   # 0.6


def test_summarize_cohort_structure():
    df = pd.DataFrame({
        "as_of_date": ["2020-06-01", "2020-06-01"],
        "pass_status": ["PASS", "WATCHLIST"],
        "grade": ["A", "B"],
        "fwd_1m": [0.25, -0.05], "fwd_3m": [0.4, 0.0], "fwd_6m": [0.5, 0.1], "fwd_12m": [0.6, 0.2],
        "C_status": ["Pass", "Fail"], "A_status": ["Pass", "Weak"], "N_status": ["Pass", "Fail"],
        "S_status": ["Pass", "Weak"], "L_status": ["Pass", "Weak"], "I_status": ["Pass", "Weak"], "M_status": ["Pass", "Pass"],
    })
    s = cb.summarize_cohort(df)
    assert s["n_rows"] == 2
    assert "PASS" in s["by_pass_status"] and "WATCHLIST" in s["by_pass_status"]
    assert s["by_pass_status"]["PASS"]["fwd_1m"]["n"] == 1
    assert "baseline_all_screened" in s and "fwd_1m" in s["baseline_all_screened"]
    assert "C" in s["by_pillar"] and "pass" in s["by_pillar"]["C"]["fwd_1m"]


def test_cohort_rows_end_to_end(tmp_path: Path, monkeypatch):
    store, dates = _store(tmp_path)
    as_of = dates[100]
    fake = ScreeningResult(
        stock_id="AAA", as_of_date=as_of, candidate_grade="A", canslim_match="7/7",
        pillars={p: "Pass" for p in "CANSLIM"}, market_regime="risk_on",
        scores={"signal": 70, "risk": 20, "confidence": 75},
        interpretation="x", action_type="Watchlist Candidate",
    )
    monkeypatch.setattr(cb, "get_universe_as_of", lambda *a, **k: ["AAA"])
    monkeypatch.setattr(cb, "_market_features_for_entry", lambda *a, **k: MarketFeatures())
    monkeypatch.setattr(cb, "_universe_returns_as_of", lambda *a, **k: {})
    monkeypatch.setattr(cb, "build_pit_inputs", lambda *a, **k: ({}, {}, None))
    monkeypatch.setattr(cb, "build_screening_result", lambda *a, **k: fake)

    df = cb._cohort_rows(store, None, load_params(), ["AAA"], [as_of])
    assert len(df) == 1
    row = df.iloc[0]
    assert row["stock_id"] == "AAA"
    assert row["pass_status"] in {"PASS", "WATCHLIST"}
    assert row["C_status"] == "Pass"
    assert abs(row["fwd_1m"] - (220.0 / 200.0 - 1.0)) < 1e-6
