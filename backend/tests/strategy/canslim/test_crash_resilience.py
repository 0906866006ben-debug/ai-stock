from __future__ import annotations

from pathlib import Path

import pandas as pd

from backend.app.services.backtest.historical_data_store import HistoricalDataStore
from backend.app.services.strategy.canslim import crash_resilience as cr
from backend.app.services.strategy.canslim.crash_resilience import CrashEvent, symbol_crash_metrics

EV = CrashEvent("test", "2018-02-01", "2018-05-01", "2018-12-31")


def _store(tmp_path: Path) -> HistoricalDataStore:
    store = HistoricalDataStore(tmp_path / "ohlcv.db")
    start = pd.Timestamp("2018-01-01")
    n = 360
    rows = []

    def add(sym, closes):
        for i, c in enumerate(closes):
            d = (start + pd.Timedelta(days=i)).strftime("%Y-%m-%d")
            rows.append({"stock_id": sym, "date": d, "open": c, "high": c, "low": c, "close": c,
                         "volume": 1_000_000, "turnover": c * 1_000_000})

    # TAIEX: dips to a trough around day ~90 (early Apr) then recovers -> trough in [t0, trough_end].
    taiex = [10000 - min(i, 90) * 30 + max(0, i - 90) * 20 for i in range(n)]
    add("TAIEX", taiex)
    # RESIL: entry ~100 at t0(day31), V-dip to 70, recovers above 100 later.
    resil = [100] * 31 + [100 - (i - 31) * 2 for i in range(31, 46)] + [70 + (i - 46) * 3 for i in range(46, n)]
    add("RESIL", resil[:n])
    # IMPAIR: drops to 30 and stays (never recovers, <50% of entry).
    impair = [100] * 31 + [100 - (i - 31) * 5 for i in range(31, 45)] + [30] * (n - 45)
    add("IMPAIR", impair[:n])
    # DELIST: drops then stops trading ~day 110 (no bars after -> delisted).
    delist = [100] * 31 + [100 - (i - 31) * 4 for i in range(31, 110)]
    add("DELIST", delist)
    store.upsert_rows(rows)
    return store


def test_resilient_name_recovers(tmp_path):
    store = _store(tmp_path)
    trough = cr._trough_date(store, EV.t0, EV.trough_end)
    m = symbol_crash_metrics(store, "RESIL", EV, trough, impair_thr=0.5, staleness_days=20)
    assert m["drawdown"] < 0          # took a hit
    assert m["recovered"] is True
    assert m["delisted"] is False and m["impaired"] is False


def test_impaired_name_does_not_recover(tmp_path):
    store = _store(tmp_path)
    trough = cr._trough_date(store, EV.t0, EV.trough_end)
    m = symbol_crash_metrics(store, "IMPAIR", EV, trough, impair_thr=0.5, staleness_days=20)
    assert m["recovered"] is False
    assert m["impaired"] is True       # stuck < 50% of entry


def test_delisted_name_flagged(tmp_path):
    store = _store(tmp_path)
    trough = cr._trough_date(store, EV.t0, EV.trough_end)
    m = symbol_crash_metrics(store, "DELIST", EV, trough, impair_thr=0.5, staleness_days=20)
    assert m["delisted"] is True
    assert m["impaired"] is True       # delisted implies permanent impairment


def test_quintiles_and_summary_q1_better():
    # Hand-built: Q1 (high durability) resilient, Q5 (low) impaired/delisted.
    rows = []
    for i in range(10):
        rows.append({"stock_id": f"H{i}", "durability": 90 - i, "trough_date": "2018-04-01",
                     "drawdown": -0.10, "recovered": True, "recovery_days": 30, "delisted": False, "impaired": False})
    for i in range(10):
        rows.append({"stock_id": f"L{i}", "durability": 40 - i, "trough_date": "2018-04-01",
                     "drawdown": -0.50, "recovered": False, "recovery_days": None, "delisted": i % 2 == 0, "impaired": True})
    df = pd.DataFrame(rows)
    df["quintile"] = cr._quintiles(df["durability"])
    summ = cr._summarize(df)
    q1, q5 = summ["by_quintile"]["Q1"], summ["by_quintile"]["Q5"]
    assert q1["median_drawdown"] > q5["median_drawdown"]    # Q1 less negative
    assert q1["pct_recovered"] > q5["pct_recovered"]
    assert q1["impairment_rate"] < q5["impairment_rate"]
    assert summ["Q1_vs_Q5"]["drawdown_gap"] > 0
