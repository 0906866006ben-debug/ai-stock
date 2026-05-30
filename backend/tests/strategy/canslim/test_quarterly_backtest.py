from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from backend.app.services.backtest.historical_data_store import HistoricalDataStore
from backend.app.services.strategy.canslim import quarterly_backtest as qb
from backend.app.services.strategy.canslim.quarterly_backtest import QuarterlyConfig


def _store(tmp_path: Path, symbols=("AAA", "TAIEX"), n=900):
    store = HistoricalDataStore(tmp_path / "ohlcv.db")
    start = pd.Timestamp("2018-01-01")
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
    return store


class _FakePit:
    """Minimal pit store exposing get_month_revenue_as_of + get_balance_sheet_as_of."""
    def __init__(self, revenue: dict[str, list[dict]], shares: dict[str, float]):
        self._rev = revenue
        self._shares = shares

    def get_month_revenue_as_of(self, stock_id, as_of_date, limit=36):
        rows = self._rev.get(str(stock_id), [])
        df = pd.DataFrame(rows)
        if df.empty:
            return df
        return df[pd.to_datetime(df["date"]) <= pd.Timestamp(as_of_date)].reset_index(drop=True)

    def get_balance_sheet_as_of(self, stock_id, as_of_date, limit=1):
        sh = self._shares.get(str(stock_id))
        if sh is None:
            return pd.DataFrame()
        return pd.DataFrame([{"period_end": as_of_date,
                              "raw_json": json.dumps([{"type": "CapitalStock", "value": sh * 10.0}])}])


def _rev_rows(pairs):
    # pairs: list of (date, year, month, revenue)
    return [{"date": d, "revenue": rev, "revenue_yoy": None, "revenue_mom": None,
             "raw_json": json.dumps({"revenue_year": y, "revenue_month": m, "revenue": rev})}
            for (d, y, m, rev) in pairs]


def test_quarterly_rebalance_dates_grid(tmp_path):
    store = _store(tmp_path, symbols=("TAIEX",), n=900)  # ~2.5 years from 2018-01-01
    dates = qb.quarterly_rebalance_dates(store, "2018-01-01", "2019-12-31")
    assert dates == sorted(dates) and len(dates) >= 6
    # each falls on/after a grid (month,day)
    for d in dates:
        ts = pd.Timestamp(d)
        assert (ts.month, ts.day) >= min(qb.REBALANCE_GRID)


def test_revenue_yoy_lag_and_math():
    # Apr-2019 revenue is dated 2019-05-01 (FinMind 1st-of-next-month); public ~05/10.
    rev = _rev_rows([
        ("2018-05-01", 2018, 4, 100.0),   # Apr-2018 rev
        ("2019-05-01", 2019, 4, 150.0),   # Apr-2019 rev -> YoY = +50%
    ])
    pit = _FakePit({"AAA": rev}, shares={})
    # as_of 2019-05-05: stored date 2019-05-01 <= 2019-05-05 BUT lag(10d) cutoff = 2019-04-25
    #   -> Apr-2019 not yet public -> latest usable is Apr-2018 only -> no YoY pair -> None.
    assert qb.revenue_yoy_as_of(pit, "AAA", "2019-05-05", lag_days=10) is None
    # as_of 2019-05-16: cutoff 2019-05-06 >= 2019-05-01 -> Apr-2019 public -> YoY +50%.
    yoy = qb.revenue_yoy_as_of(pit, "AAA", "2019-05-16", lag_days=10)
    assert yoy is not None and abs(yoy - 0.50) < 1e-9


def test_basket_quarter_return_applies_cost(tmp_path):
    store = _store(tmp_path, symbols=("AAA", "TAIEX"))
    cfg = QuarterlyConfig(arm="ni", round_trip_cost=0.005, slippage=0.002)
    # entry 2018-01-01+100d close=200, exit +120d close=220 -> gross 0.10
    entry = (pd.Timestamp("2018-01-01") + pd.Timedelta(days=100)).strftime("%Y-%m-%d")
    exit_ = (pd.Timestamp("2018-01-01") + pd.Timedelta(days=120)).strftime("%Y-%m-%d")
    net, n = qb.basket_quarter_return(store, ["AAA"], entry, exit_, cfg)
    assert n == 1
    assert abs(net - (0.10 - 0.007)) < 1e-6


def test_daily_mtm_captures_intra_quarter_dip(tmp_path):
    store = HistoricalDataStore(tmp_path / "ohlcv.db")
    start = pd.Timestamp("2020-01-01")
    n = 40
    # V-shaped price: 100 -> ~70 trough -> recover to 108. Quarterly-point sampling (entry
    # 100, exit 108) would report ZERO drawdown; daily MTM must see the -30% trough.
    prices = [100, 98, 92, 85, 78, 72, 70, 75, 82, 90, 95, 98, 100, 101, 102, 103, 104, 105, 106, 107] + [108] * 20
    rows = []
    for i in range(n):
        d = (start + pd.Timedelta(days=i)).strftime("%Y-%m-%d")
        rows.append({"stock_id": "TAIEX", "date": d, "open": 1000, "high": 1000, "low": 1000, "close": 1000, "volume": 1, "turnover": 1000})
        c = prices[i]
        rows.append({"stock_id": "DIP", "date": d, "open": c, "high": c, "low": c, "close": c, "volume": 1, "turnover": c})
    store.upsert_rows(rows)
    entry = start.strftime("%Y-%m-%d")
    exit_ = (start + pd.Timedelta(days=n - 1)).strftime("%Y-%m-%d")
    cfg = QuarterlyConfig(arm="ni", round_trip_cost=0.0, slippage=0.0)
    eq_rows, end_eq, n_held = qb._quarter_daily_equity(store, ["DIP"], entry, exit_, 1.0, cfg)
    assert n_held == 1
    equities = [r["equity"] for r in eq_rows]
    assert min(equities) < 0.80          # daily MTM saw the ~-30% intra-quarter trough
    assert end_eq > min(equities)        # recovered by quarter end (quarterly sampling would miss the dip)


def test_select_basket_two_arms():
    ranked = pd.DataFrame({
        "stock_id": ["AAA", "BBB", "CCC", "DDD"],
        "overall_score": [90, 80, 70, 60],          # already sorted desc
        "C_status": ["Pass", "Pass", "Pass", "Fail"],
        "A_status": ["Pass", "Pass", "Pass", "Pass"],
    })
    # all C/A Pass except DDD (C Fail -> excluded). G passes for AAA/BBB/CCC.
    rev = {s: _rev_rows([("2018-05-01", 2018, 4, 100.0), ("2019-05-01", 2019, 4, 130.0)]) for s in ("AAA", "BBB", "CCC")}
    pit = _FakePit(rev, shares={"AAA": 5e9, "BBB": 1e9, "CCC": 9e9})  # BBB smallest float
    base = dict(basket_size=2, min_revenue_yoy=0.10, revenue_publish_lag_days=10)
    ni = qb.select_basket(ranked, pit, "2019-05-16", QuarterlyConfig(arm="ni", **base))
    video = qb.select_basket(ranked, pit, "2019-05-16", QuarterlyConfig(arm="video", **base))
    assert ni == ["AAA", "BBB"]               # top score, C/A/G ok
    assert video[0] == "BBB"                   # smallest float first
    assert "DDD" not in ni and "DDD" not in video   # C Fail gated out
