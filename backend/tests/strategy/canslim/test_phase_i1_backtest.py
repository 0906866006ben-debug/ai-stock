from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from backend.app.services.backtest.historical_data_store import HistoricalDataStore
from backend.app.services.backtest.signal_replay import CANSLIM_CANDIDATE_TYPE, ReplayConfig, load_signals, replay_signals
from backend.app.services.backtest.trade_simulator import canslim_trade_rules_from_params, load_trades, simulate_trades
from backend.app.services.strategy.canslim.types import MarketFeatures


AS_OF = "2024-09-16"


def test_canslim_replay_produces_nonzero_signals(tmp_path: Path):
    store = _canslim_store(tmp_path)
    summary = replay_signals(_canslim_config("i1_signals"), data_store=store, db_path=tmp_path / "i1.db")
    signals = load_signals(tmp_path / "i1.db", "i1_signals")

    assert summary.by_type[CANSLIM_CANDIDATE_TYPE] > 0
    assert len(signals) > 0
    assert set(signals["candidate_type"]) == {CANSLIM_CANDIDATE_TYPE}
    assert signals["canslim_grade"].isin(["S", "A", "B"]).all()
    assert signals["canslim_signal_raw"].gt(0).all()


def test_canslim_trade_simulation_produces_trade_and_applies_round_trip_cost(tmp_path: Path):
    store = _canslim_store(tmp_path)
    db_path = tmp_path / "i1_trade.db"
    replay_signals(_canslim_config("i1_trades"), data_store=store, db_path=db_path)
    signals = load_signals(db_path, "i1_trades")

    summary = simulate_trades(
        signals_df=signals,
        data_store=store,
        rules=canslim_trade_rules_from_params(),
        run_id="i1_trades",
        db_path=db_path,
    )
    trades = load_trades(db_path, "i1_trades")
    filled = trades[trades["entry_status"] == "filled"]

    assert summary.trades_filled >= 1
    assert len(filled) >= 1
    first = filled.iloc[0]
    rules = canslim_trade_rules_from_params()
    assert first["candidate_type"] == CANSLIM_CANDIDATE_TYPE
    assert first["net_return_pct"] == pytest.approx(first["gross_return_pct"] - rules.round_trip_cost_pct, abs=1e-6)


def test_canslim_pit_eps_filing_date_does_not_leak_future_eps(tmp_path: Path):
    store = _eps_only_store(tmp_path)
    db_path = tmp_path / "i1_pit.db"
    future_cfg = _eps_only_config("pit_future", eps_filing_date="2024-09-20")
    past_cfg = _eps_only_config("pit_past", eps_filing_date="2024-09-01")

    future_summary = replay_signals(future_cfg, data_store=store, db_path=db_path)
    past_summary = replay_signals(past_cfg, data_store=store, db_path=db_path)

    assert future_summary.by_type[CANSLIM_CANDIDATE_TYPE] == 0
    assert past_summary.by_type[CANSLIM_CANDIDATE_TYPE] >= 1


def test_default_replay_config_keeps_legacy_candidate_path(tmp_path: Path):
    store = _canslim_store(tmp_path)
    db_path = tmp_path / "legacy.db"
    config = ReplayConfig(
        run_id="legacy_default",
        start_date=AS_OF,
        end_date=AS_OF,
        stock_universe=["STRONG"],
    )

    summary = replay_signals(config, data_store=store, db_path=db_path)
    signals = load_signals(db_path, "legacy_default")

    assert config.target_candidate_types == ["起漲前觀察"]
    assert CANSLIM_CANDIDATE_TYPE not in summary.by_type
    if not signals.empty:
        assert CANSLIM_CANDIDATE_TYPE not in set(signals["candidate_type"])


def _canslim_config(run_id: str) -> ReplayConfig:
    return ReplayConfig(
        run_id=run_id,
        start_date=AS_OF,
        end_date=AS_OF,
        stock_universe=["STRONG", "WEAK"],
        target_candidate_types=[CANSLIM_CANDIDATE_TYPE],
        lookback_bars=280,
        canslim_market=_market(),
        canslim_fin_metrics_by_stock={
            "STRONG": _strong_fin(),
            "WEAK": _weak_fin(),
        },
        canslim_detail_by_stock={
            "STRONG": _strong_detail(),
            "WEAK": _weak_detail(),
        },
        canslim_universe_returns_60d={"STRONG": 0.8, "WEAK": 0.1},
        canslim_universe_returns_252d={"STRONG": 0.8, "WEAK": 0.1},
        canslim_eps_filing_dates_by_stock={"STRONG": "2024-09-01", "WEAK": "2024-09-01"},
        canslim_event_window_by_stock={"STRONG": False, "WEAK": False},
    )


def _eps_only_config(run_id: str, *, eps_filing_date: str) -> ReplayConfig:
    return ReplayConfig(
        run_id=run_id,
        start_date=AS_OF,
        end_date=AS_OF,
        stock_universe=["EPSONLY"],
        target_candidate_types=[CANSLIM_CANDIDATE_TYPE],
        lookback_bars=280,
        canslim_market=_market(),
        canslim_fin_metrics_by_stock={"EPSONLY": _eps_only_fin()},
        canslim_detail_by_stock={"EPSONLY": {"month_revenue_yoy": [0.18, 0.22, 0.30]}},
        canslim_universe_returns_60d={"EPSONLY": 0.1, "LEADER": 0.9},
        canslim_universe_returns_252d={"EPSONLY": 0.1, "LEADER": 0.9},
        canslim_eps_filing_dates_by_stock={"EPSONLY": eps_filing_date},
        canslim_event_window_by_stock={"EPSONLY": False},
    )


def _canslim_store(tmp_path: Path) -> HistoricalDataStore:
    store = HistoricalDataStore(tmp_path / "canslim_i1.db")
    rows = []
    rows.extend(_trend_rows("STRONG", base=80.0, slope=0.22, final_jump=8.0, turnover=80_000_000))
    rows.extend(_trend_rows("WEAK", base=50.0, slope=0.01, final_jump=0.0, turnover=40_000_000))
    store.upsert_rows(rows)
    return store


def _eps_only_store(tmp_path: Path) -> HistoricalDataStore:
    store = HistoricalDataStore(tmp_path / "canslim_i1_pit.db")
    store.upsert_rows(_trend_rows("EPSONLY", base=100.0, slope=0.0, final_jump=0.0, turnover=80_000_000, prior_spike=True))
    return store


def _trend_rows(
    symbol: str,
    *,
    base: float,
    slope: float,
    final_jump: float,
    turnover: float,
    prior_spike: bool = False,
) -> list[dict]:
    start = pd.Timestamp("2024-01-01")
    rows = []
    for idx in range(280):
        day = start + pd.Timedelta(days=idx)
        close = base + slope * idx
        if prior_spike and idx == 120:
            close = base * 1.4
        if idx == 259:
            close += final_jump
        if idx > 259:
            close = base + slope * 259 + final_jump + (idx - 259) * 1.0
        volume = 1200.0
        if idx == 259 and final_jump:
            volume = 2600.0
        rows.append(
            {
                "stock_id": symbol,
                "date": day.strftime("%Y-%m-%d"),
                "open": close,
                "high": close,
                "low": close * 0.99,
                "close": close,
                "volume": volume,
                "turnover": turnover,
            }
        )
    return rows


def _market() -> MarketFeatures:
    return MarketFeatures(
        taiex_close=20_000,
        taiex_ma150=19_000,
        taiex_ma150_slope=0.01,
        tpex_close=250,
        tpex_ma150=240,
        tpex_ma150_slope=0.01,
        breadth_above_ma60_pct=0.7,
        sox_above_ma60=True,
        nasdaq_above_ma60=True,
    )


def _strong_fin() -> dict:
    return {
        "eps_yoy": 0.35,
        "annual_eps": [10.0, 12.0, 16.0],
        "roe": 20.0,
        "op_margin_last4": [20.0, 21.0, 22.0, 23.0],
        "pe_ttm": 30.0,
    }


def _weak_fin() -> dict:
    return {
        "eps_yoy": 0.05,
        "annual_eps": [10.0, 10.0, 10.0],
        "roe": 5.0,
        "op_margin_last4": [20.0, 19.0, 18.0, 17.0],
        "pe_ttm": 45.0,
    }


def _eps_only_fin() -> dict:
    return {
        "eps_yoy": 0.35,
        "annual_eps": [10.0, 10.0, 10.0],
        "roe": 5.0,
        "op_margin_last4": [20.0, 19.0, 18.0, 17.0],
        "pe_ttm": 20.0,
    }


def _strong_detail() -> dict:
    return {
        "month_revenue_yoy": [0.18, 0.22, 0.30],
        "foreign_net_5": [1, 2, 30, 30, 30],
        "trust_net_5": [1, 2, 3, 4, 5],
        "dealer_net_5": [0, 0, 0, 0, 0],
    }


def _weak_detail() -> dict:
    return {
        "month_revenue_yoy": [0.01, 0.01, 0.02],
        "foreign_net_5": [-1, -1, -1, -1, -1],
        "trust_net_5": [-1, -1, -1, -1, -1],
        "dealer_net_5": [0, 0, 0, 0, 0],
    }
