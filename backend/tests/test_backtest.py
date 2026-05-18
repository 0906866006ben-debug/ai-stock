"""Backtest framework tests.

The most critical test is `test_no_lookahead_bias` — if this fails the entire
backtest is invalid because we'd be using future data to make past decisions.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd
import pytest

from backend.app.services.backtest.historical_data_store import HistoricalDataStore
from backend.app.services.backtest.metrics import compute_equity_curve, compute_metrics, group_metrics_by
from backend.app.services.backtest.report_generator import generate_markdown_report
from backend.app.services.backtest.signal_replay import (
    ReplayConfig,
    generate_run_id,
    load_signals,
    replay_signals,
)
from backend.app.services.backtest.trade_simulator import (
    EntryStatus,
    ExitReason,
    TradeRules,
    load_trades,
    simulate_trades,
)


# ───────────────────────────────────────────────────────────────────────────
# Fixtures
# ───────────────────────────────────────────────────────────────────────────

@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    return tmp_path / "test_backtest.db"


@pytest.fixture
def store_with_synthetic_data(temp_db: Path) -> HistoricalDataStore:
    """Build 200 days of synthetic OHLCV for 2 stocks, with one having pre-breakout pattern."""
    store = HistoricalDataStore(temp_db)

    rows: list[dict] = []
    # Stock A: simulated bull-flag pattern — rally then consolidate
    base_date = pd.Timestamp("2023-01-01")
    for i in range(200):
        date = (base_date + pd.Timedelta(days=i)).strftime("%Y-%m-%d")
        # First 60 days: rally from 100 to 115
        # Next 80 days: consolidate around 108-115
        # Last 60 days: gradual decline to 108 (the "shakeout")
        if i < 60:
            close = 100 + (i / 60) * 15
        elif i < 140:
            import math
            close = 112 + 3 * math.sin(i / 5)
        else:
            close = 110 - ((i - 140) / 60) * 2
        rows.append({
            "stock_id": "AAA",
            "date": date,
            "open": close * 0.998,
            "high": close * 1.012,
            "low": close * 0.988,
            "close": close,
            "volume": 1500,
            "turnover": close * 1500 * 1000 * 100,  # 100M+
        })
        rows.append({
            "stock_id": "BBB",
            "date": date,
            "open": 50.0,
            "high": 50.5,
            "low": 49.5,
            "close": 50.0,
            "volume": 100,
            "turnover": 5_000_000,
        })

    store.upsert_rows(rows)
    return store


# ───────────────────────────────────────────────────────────────────────────
# HistoricalDataStore tests
# ───────────────────────────────────────────────────────────────────────────

def test_store_upsert_and_read(temp_db: Path) -> None:
    store = HistoricalDataStore(temp_db)
    rows = [
        {"stock_id": "2330", "date": "2024-01-02", "open": 600.0, "high": 605.0,
         "low": 598.0, "close": 603.0, "volume": 30000, "turnover": 1_810_000_000},
        {"stock_id": "2330", "date": "2024-01-03", "open": 604.0, "high": 610.0,
         "low": 601.0, "close": 608.0, "volume": 28000, "turnover": 1_701_000_000},
    ]
    assert store.upsert_rows(rows) == 2
    df = store.get_ohlcv("2330", "2024-01-01", "2024-01-31")
    assert len(df) == 2
    assert df["close"].iloc[-1] == 608.0


def test_get_ohlcv_as_of_returns_only_past_bars(temp_db: Path) -> None:
    """POINT-IN-TIME critical: get_ohlcv_as_of must not include rows after the cutoff."""
    store = HistoricalDataStore(temp_db)
    rows = [
        {"stock_id": "X", "date": d, "open": 100, "high": 100, "low": 100, "close": 100, "volume": 1000, "turnover": 100000}
        for d in ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08"]
    ]
    store.upsert_rows(rows)

    # As-of 2024-01-04 with lookback 10: should return [01-02, 01-03, 01-04]
    df = store.get_ohlcv_as_of("X", "2024-01-04", 10)
    assert len(df) == 3
    assert df["date"].iloc[-1] == "2024-01-04"
    assert "2024-01-05" not in df["date"].values
    assert "2024-01-08" not in df["date"].values


def test_store_idempotent_upsert(temp_db: Path) -> None:
    store = HistoricalDataStore(temp_db)
    rows = [{"stock_id": "X", "date": "2024-01-02", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1, "turnover": 1}]
    store.upsert_rows(rows)
    rows[0]["close"] = 999.0
    store.upsert_rows(rows)  # second upsert should update, not duplicate
    df = store.get_ohlcv("X", "2024-01-01", "2024-12-31")
    assert len(df) == 1
    assert df["close"].iloc[0] == 999.0


# ───────────────────────────────────────────────────────────────────────────
# Signal replay tests — LOOKAHEAD BIAS critical
# ───────────────────────────────────────────────────────────────────────────

def test_no_lookahead_bias_in_signal_replay(store_with_synthetic_data: HistoricalDataStore, temp_db: Path) -> None:
    """The KEY test: signals generated for date D must only use data with date <= D.

    We tamper with the future after replay — if replay had peeked at the future,
    the original signals would be different. We verify they're the same.
    """
    config = ReplayConfig(
        run_id="lookahead_check",
        start_date="2023-04-01",
        end_date="2023-04-10",
        stock_universe=["AAA"],
        target_candidate_types=["起漲前觀察", "初動候選", "動能確認", "偏熱觀察"],  # capture anything
    )
    replay_signals(config, data_store=store_with_synthetic_data, db_path=temp_db)
    signals_before = load_signals(temp_db, "lookahead_check")

    # Tamper with future bars (post 2023-04-10)
    future_rows = [
        {"stock_id": "AAA", "date": "2023-04-11", "open": 999, "high": 999,
         "low": 999, "close": 999, "volume": 99999, "turnover": 999_999_999_999}
    ]
    store_with_synthetic_data.upsert_rows(future_rows)

    # Re-run replay
    config_after = ReplayConfig(
        run_id="lookahead_check_after",
        start_date="2023-04-01",
        end_date="2023-04-10",
        stock_universe=["AAA"],
        target_candidate_types=["起漲前觀察", "初動候選", "動能確認", "偏熱觀察"],
    )
    replay_signals(config_after, data_store=store_with_synthetic_data, db_path=temp_db)
    signals_after = load_signals(temp_db, "lookahead_check_after")

    # If no lookahead, modifying 2023-04-11 should NOT change signals from 2023-04-01 to 2023-04-10
    if not signals_before.empty and not signals_after.empty:
        cols = ["signal_date", "stock_id", "candidate_type", "surge_candidate_score"]
        b = signals_before[cols].sort_values(cols).reset_index(drop=True)
        a = signals_after[cols].sort_values(cols).reset_index(drop=True)
        pd.testing.assert_frame_equal(a, b)
    else:
        # Both empty is OK — same outcome
        assert signals_before.empty and signals_after.empty


# ───────────────────────────────────────────────────────────────────────────
# Trade simulator tests
# ───────────────────────────────────────────────────────────────────────────

def test_trade_simulator_stop_loss_triggered(store_with_synthetic_data: HistoricalDataStore, temp_db: Path) -> None:
    """Stock crashing -10% should trigger stop-loss exit."""
    # Add a stock that crashes after our signal date
    rows = [
        {"stock_id": "CRASH", "date": "2023-06-01", "open": 100, "high": 100, "low": 100, "close": 100, "volume": 1000, "turnover": 100_000_000},
        # Next day open is 95, low touches 85 (stop should fire)
        {"stock_id": "CRASH", "date": "2023-06-02", "open": 95, "high": 96, "low": 85, "close": 88, "volume": 1000, "turnover": 100_000_000},
        {"stock_id": "CRASH", "date": "2023-06-05", "open": 88, "high": 90, "low": 80, "close": 82, "volume": 1000, "turnover": 100_000_000},
    ]
    store_with_synthetic_data.upsert_rows(rows)

    signals_df = pd.DataFrame([{
        "run_id": "crash_test", "signal_date": "2023-06-01", "stock_id": "CRASH",
        "candidate_type": "起漲前觀察", "close_price": 100.0,
        "sector_category": "cat_3_packaging",
    }])

    summary = simulate_trades(
        signals_df=signals_df, data_store=store_with_synthetic_data,
        rules=TradeRules(max_hold_days=20, stop_loss_pct=0.07, target_pct=0.20),
        run_id="crash_test", db_path=temp_db,
    )
    trades = load_trades(temp_db, "crash_test")
    assert len(trades) == 1
    assert trades["exit_reason"].iloc[0] == ExitReason.STOP_LOSS.value
    assert trades["net_return_pct"].iloc[0] < -0.07   # at least -7% before fees


def test_trade_simulator_target_reached(store_with_synthetic_data: HistoricalDataStore, temp_db: Path) -> None:
    """Stock rising +20% should trigger target exit."""
    rows = [
        {"stock_id": "MOON", "date": "2023-07-01", "open": 100, "high": 100, "low": 100, "close": 100, "volume": 1000, "turnover": 100_000_000},
        {"stock_id": "MOON", "date": "2023-07-02", "open": 102, "high": 125, "low": 102, "close": 120, "volume": 1000, "turnover": 100_000_000},
        {"stock_id": "MOON", "date": "2023-07-03", "open": 121, "high": 123, "low": 119, "close": 122, "volume": 1000, "turnover": 100_000_000},
    ]
    store_with_synthetic_data.upsert_rows(rows)

    signals_df = pd.DataFrame([{
        "run_id": "moon_test", "signal_date": "2023-07-01", "stock_id": "MOON",
        "candidate_type": "起漲前觀察", "close_price": 100.0,
        "sector_category": "cat_1_silicon_ip",
    }])

    simulate_trades(
        signals_df=signals_df, data_store=store_with_synthetic_data,
        rules=TradeRules(max_hold_days=20, stop_loss_pct=0.07, target_pct=0.15),
        run_id="moon_test", db_path=temp_db,
    )
    trades = load_trades(temp_db, "moon_test")
    assert len(trades) == 1
    assert trades["exit_reason"].iloc[0] == ExitReason.TARGET_REACHED.value
    assert trades["net_return_pct"].iloc[0] > 0.10


def test_trade_simulator_hold_days_expired(store_with_synthetic_data: HistoricalDataStore, temp_db: Path) -> None:
    """Stock drifting sideways should exit on max_hold_days."""
    rows = [
        {"stock_id": "FLAT", "date": "2023-08-01", "open": 100, "high": 100, "low": 100, "close": 100, "volume": 1000, "turnover": 100_000_000},
    ]
    # 25 days of sideways action
    for i in range(1, 26):
        dt = pd.Timestamp("2023-08-01") + pd.Timedelta(days=i)
        rows.append({
            "stock_id": "FLAT", "date": dt.strftime("%Y-%m-%d"),
            "open": 101, "high": 102, "low": 99, "close": 101,
            "volume": 1000, "turnover": 100_000_000,
        })
    store_with_synthetic_data.upsert_rows(rows)

    signals_df = pd.DataFrame([{
        "run_id": "flat_test", "signal_date": "2023-08-01", "stock_id": "FLAT",
        "candidate_type": "起漲前觀察", "close_price": 100.0,
        "sector_category": "cat_4_components",
    }])

    simulate_trades(
        signals_df=signals_df, data_store=store_with_synthetic_data,
        rules=TradeRules(max_hold_days=10, stop_loss_pct=0.07, target_pct=0.15),
        run_id="flat_test", db_path=temp_db,
    )
    trades = load_trades(temp_db, "flat_test")
    assert len(trades) == 1
    assert trades["exit_reason"].iloc[0] == ExitReason.HOLD_DAYS.value
    assert trades["hold_days"].iloc[0] == 10


def test_trade_simulator_skipped_when_no_next_day_data(store_with_synthetic_data: HistoricalDataStore, temp_db: Path) -> None:
    """Signal on last available date → should be skipped (no next-day fill)."""
    signals_df = pd.DataFrame([{
        "run_id": "skip_test", "signal_date": "2099-12-31", "stock_id": "NOWHERE",
        "candidate_type": "起漲前觀察", "close_price": 100.0, "sector_category": None,
    }])

    simulate_trades(
        signals_df=signals_df, data_store=store_with_synthetic_data,
        rules=TradeRules(), run_id="skip_test", db_path=temp_db,
    )
    trades = load_trades(temp_db, "skip_test")
    assert len(trades) == 1
    assert trades["entry_status"].iloc[0] == EntryStatus.SKIPPED_NO_NEXT_DAY.value


# ───────────────────────────────────────────────────────────────────────────
# Metrics tests
# ───────────────────────────────────────────────────────────────────────────

def test_metrics_on_known_trades() -> None:
    """Trade dataset with known returns → verify all metrics by hand."""
    trades = pd.DataFrame([
        {"entry_status": "filled", "net_return_pct": 0.10, "hold_days": 5, "exit_date": "2024-01-05"},
        {"entry_status": "filled", "net_return_pct": -0.05, "hold_days": 8, "exit_date": "2024-01-10"},
        {"entry_status": "filled", "net_return_pct": 0.12, "hold_days": 6, "exit_date": "2024-01-15"},
        {"entry_status": "filled", "net_return_pct": -0.03, "hold_days": 4, "exit_date": "2024-01-19"},
        {"entry_status": "filled", "net_return_pct": 0.08, "hold_days": 10, "exit_date": "2024-01-29"},
    ])
    m = compute_metrics(trades)
    assert m.n_trades == 5
    assert m.win_rate == pytest.approx(3/5)
    # Average: (0.10 - 0.05 + 0.12 - 0.03 + 0.08) / 5 = 0.044
    assert m.avg_return == pytest.approx(0.044, abs=1e-4)
    # Profit factor: 0.30 / 0.08 = 3.75
    assert m.profit_factor == pytest.approx(3.75, abs=1e-2)


def test_metrics_handles_empty_trades() -> None:
    empty = pd.DataFrame(columns=["entry_status", "net_return_pct", "hold_days", "exit_date"])
    m = compute_metrics(empty)
    assert m.n_trades == 0
    assert m.win_rate == 0
    assert m.sharpe == 0


def test_equity_curve_compounds_returns() -> None:
    trades = pd.DataFrame([
        {"trade_id": 1, "entry_status": "filled", "net_return_pct": 0.10, "exit_date": "2024-01-05"},
        {"trade_id": 2, "entry_status": "filled", "net_return_pct": 0.10, "exit_date": "2024-01-10"},
    ])
    eq = compute_equity_curve(trades, initial_capital=1_000_000)
    # 1M * 1.1 * 1.1 = 1.21M
    assert eq["equity"].iloc[-1] == pytest.approx(1_210_000.0, abs=1.0)


def test_group_metrics_by_sector() -> None:
    trades = pd.DataFrame([
        {"entry_status": "filled", "net_return_pct": 0.10, "hold_days": 5, "exit_date": "2024-01-05", "sector_category": "cat_1_silicon_ip"},
        {"entry_status": "filled", "net_return_pct": 0.12, "hold_days": 6, "exit_date": "2024-01-12", "sector_category": "cat_1_silicon_ip"},
        {"entry_status": "filled", "net_return_pct": -0.03, "hold_days": 4, "exit_date": "2024-01-04", "sector_category": "cat_3_packaging"},
    ])
    grouped = group_metrics_by(trades, "sector_category")
    assert len(grouped) == 2
    cat_1 = grouped[grouped["sector_category"] == "cat_1_silicon_ip"].iloc[0]
    assert cat_1["n_trades"] == 2
    assert cat_1["win_rate"] == 1.0


# ───────────────────────────────────────────────────────────────────────────
# Report generation test
# ───────────────────────────────────────────────────────────────────────────

def test_report_generator_outputs_markdown() -> None:
    trades = pd.DataFrame([
        {"trade_id": 1, "stock_id": "2330", "signal_date": "2024-01-01",
         "entry_date": "2024-01-02", "exit_date": "2024-01-08",
         "entry_price": 600.0, "exit_price": 660.0, "exit_reason": "target_reached",
         "hold_days": 5, "gross_return_pct": 0.10, "net_return_pct": 0.095,
         "entry_status": "filled", "candidate_type": "起漲前觀察", "sector_category": "cat_2_foundry"},
        {"trade_id": 2, "stock_id": "6669", "signal_date": "2024-02-01",
         "entry_date": "2024-02-02", "exit_date": "2024-02-15",
         "entry_price": 2000.0, "exit_price": 1860.0, "exit_reason": "stop_loss_triggered",
         "hold_days": 10, "gross_return_pct": -0.07, "net_return_pct": -0.075,
         "entry_status": "filled", "candidate_type": "起漲前觀察", "sector_category": "cat_5_system_integration"},
    ])
    config = {"run_id": "test_run", "date_range": "2024-01-01 → 2024-12-31"}
    report = generate_markdown_report(run_id="test_run", config_summary=config, trades_df=trades)
    assert "# 📊 Backtest Report" in report
    assert "Win Rate" in report
    assert "Profit Factor" in report
    assert "Sector Breakdown" in report
    assert "Top 5 Winners" in report


# ───────────────────────────────────────────────────────────────────────────
# End-to-end smoke test
# ───────────────────────────────────────────────────────────────────────────

def test_end_to_end_smoke(store_with_synthetic_data: HistoricalDataStore, temp_db: Path) -> None:
    """Replay → simulate → report — full pipeline runs without crash."""
    config = ReplayConfig(
        run_id="e2e_smoke",
        start_date="2023-04-01",
        end_date="2023-05-30",
        stock_universe=["AAA"],
        target_candidate_types=["起漲前觀察", "初動候選", "動能確認", "偏熱觀察", "初動觀察"],
    )
    summary = replay_signals(config, data_store=store_with_synthetic_data, db_path=temp_db)
    assert summary.run_id == "e2e_smoke"
    assert summary.days_processed > 0

    signals = load_signals(temp_db, "e2e_smoke")
    # Even if no signals, simulator should handle it gracefully
    if not signals.empty:
        sim_summary = simulate_trades(
            signals_df=signals, data_store=store_with_synthetic_data,
            rules=TradeRules(), run_id="e2e_smoke", db_path=temp_db,
        )
        assert sim_summary.run_id == "e2e_smoke"
        trades = load_trades(temp_db, "e2e_smoke")
        report = generate_markdown_report(run_id="e2e_smoke", config_summary={"test": "yes"}, trades_df=trades)
        assert "Backtest Report" in report
