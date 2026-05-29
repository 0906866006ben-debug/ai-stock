"""Swing backtest: exit precedence, costs, entry=PASS-only, by-regime aggregation."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from backend.app.services.backtest.historical_data_store import HistoricalDataStore
from backend.app.services.strategy.canslim import swing_backtest as sb
from backend.app.services.strategy.canslim.swing_backtest import SwingRules, simulate_swing_trade, _metrics


def _store(tmp_path, closes, highs=None, lows=None):
    store = HistoricalDataStore(tmp_path / "o.db")
    start = pd.Timestamp("2024-01-01")
    rows = []
    for i, c in enumerate(closes):
        hi = c if highs is None else highs[i]
        lo = c if lows is None else lows[i]
        rows.append({"stock_id": "X", "date": (start + pd.Timedelta(days=i)).strftime("%Y-%m-%d"),
                     "open": c, "high": hi, "low": lo, "close": c, "volume": 1000, "turnover": c * 1000})
    store.upsert_rows(rows)
    return store, (start + pd.Timedelta(days=29)).strftime("%Y-%m-%d")  # as_of = day 30


def _rules(**ov):
    base = dict(stop_pct=0.08, target_pct=0.25, exit_ma_days=5, max_hold_days=60, round_trip_cost_pct=0.0, slippage_pct=0.0)
    base.update(ov)
    return SwingRules(**base)


def test_target_exit_fires():
    # flat ~100 for 30 bars (as_of day30), then jumps so high>=125 target.
    closes = [100.0] * 31 + [130.0] * 5
    highs = [100.0] * 31 + [130.0] * 5
    import tempfile
    tp = Path(tempfile.mkdtemp())
    store, as_of = _store(tp, closes, highs=highs)
    t = simulate_swing_trade(store, "X", as_of, _rules())
    assert t is not None and t["exit_reason"] == "target"
    assert abs(t["net_return"] - 0.25) < 1e-6  # +25% target, zero cost


def test_stop_exit_fires():
    closes = [100.0] * 31 + [90.0] * 5
    lows = [100.0] * 31 + [90.0] * 5
    import tempfile
    tp = Path(tempfile.mkdtemp())
    store, as_of = _store(tp, closes, lows=lows)
    t = simulate_swing_trade(store, "X", as_of, _rules())
    assert t["exit_reason"] == "stop_loss"
    assert abs(t["net_return"] - (-0.08)) < 1e-6


def test_ma_break_exit_fires():
    # rise then a mild drop below the 5-day MA but not hitting the 8% stop.
    closes = [100, 101, 102, 103, 104, 105, 106, 107, 108, 109] + [110.0] * 21 + [106.0, 106.0, 106.0]
    import tempfile
    tp = Path(tempfile.mkdtemp())
    store, as_of = _store(tp, [float(c) for c in closes])
    t = simulate_swing_trade(store, "X", as_of, _rules())
    assert t["exit_reason"] in {"ma_break", "max_hold", "target", "stop_loss"}
    # specifically a modest dip should be ma_break, not stop (drop ~3.6% < 8%)
    assert t["exit_reason"] == "ma_break"


def test_no_forward_data_returns_none():
    import tempfile
    tp = Path(tempfile.mkdtemp())
    store, _ = _store(tp, [100.0] * 31)
    assert simulate_swing_trade(store, "X", "2025-01-01", _rules()) is None


def test_metrics_pf_and_winrate():
    m = _metrics([0.3, -0.1, 0.25, -0.2, 0.6])
    assert m["n"] == 5
    assert m["win_rate"] == 0.6
    # PF = (0.3+0.25+0.6)/(0.1+0.2) = 1.15/0.3
    assert abs(m["profit_factor"] - round(1.15 / 0.3, 3)) < 1e-6
    assert m["pct_gt20"] == 0.6  # 0.3,0.25,0.6


def test_collect_trades_only_takes_pass(monkeypatch, tmp_path):
    # Two symbols with identical price paths; only PASSER screens PASS -> 1 trade.
    store = HistoricalDataStore(tmp_path / "o.db")
    start = pd.Timestamp("2024-01-01")
    closes = [100.0] * 31 + [130.0] * 5
    rows = []
    for sym in ("PASSER", "FAILER"):
        for i, c in enumerate(closes):
            rows.append({"stock_id": sym, "date": (start + pd.Timedelta(days=i)).strftime("%Y-%m-%d"),
                         "open": c, "high": c, "low": c, "close": c, "volume": 1000, "turnover": c * 1000})
    store.upsert_rows(rows)
    as_of = (start + pd.Timedelta(days=29)).strftime("%Y-%m-%d")

    class FakeFull:
        def __init__(self, status): self.pass_status = status; self.grade = "A"

    class FakeResult:
        market_regime = "risk_on"

    monkeypatch.setattr(sb, "get_universe_as_of", lambda *a, **k: ["PASSER", "FAILER"])
    monkeypatch.setattr(sb, "_market_features_for_entry", lambda *a, **k: None)
    monkeypatch.setattr(sb, "_universe_returns_as_of", lambda *a, **k: {})
    monkeypatch.setattr(sb, "universe_shares_as_of", lambda *a, **k: {})
    monkeypatch.setattr(sb, "build_pit_inputs", lambda *a, **k: ({}, {}, None))
    monkeypatch.setattr(sb, "build_screening_result", lambda symbol, *a, **k: FakeResult())

    # First screened symbol PASS, second FAIL (build_full_result sees the result, not
    # the symbol, so key off call order over the fixed universe).
    seen = {"i": 0}
    def fake_full(r, params=None):
        seen["i"] += 1
        return FakeFull("PASS" if seen["i"] == 1 else "FAIL")
    monkeypatch.setattr(sb, "build_full_result", fake_full)

    df = sb._collect_trades(store, None, sb.load_params(), ["PASSER", "FAILER"], [as_of], _rules())
    assert len(df) == 1  # only the PASS symbol traded
    assert df.iloc[0]["stock_id"] == "PASSER"
