from __future__ import annotations

import pandas as pd
import pytest

from backend.app.services.strategy.canslim.portfolio_sim import (
    OverlayConfig,
    build_overlay_report,
    prepare_trades,
    simulate_portfolio,
)
from backend.app.services.strategy.canslim.params import load_params


def _trades(rows: list[dict]) -> pd.DataFrame:
    base = {
        "window": "year_2024",
        "segment": "year_2024",
        "named_cycle": "other",
        "horizon": "swing_term",
        "grade": "B",
        "regime_bucket_at_entry": "risk_on",
        "holding_days": 1,
    }
    return pd.DataFrame([{**base, **row} for row in rows])


def test_equity_curve_metrics_known_answers():
    trades = _trades(
        [
            {"stock_id": "A", "entry_date": "2024-01-01", "net_return_pct": 0.10},
            {"stock_id": "B", "entry_date": "2024-01-03", "net_return_pct": -0.20},
        ]
    )

    result = simulate_portfolio(trades, config=OverlayConfig(max_concurrent=1))

    assert result.equity_curve["equity"].iloc[-1] == pytest.approx(0.88)
    assert result.metrics["accepted_trades"] == 2
    assert result.metrics["max_drawdown"] == pytest.approx(-0.2)
    assert result.metrics["calmar"] < 0


def test_concurrency_cap_skips_entries_when_full():
    trades = _trades(
        [
            {"stock_id": "A", "entry_date": "2024-01-01", "holding_days": 5, "net_return_pct": 0.10},
            {"stock_id": "B", "entry_date": "2024-01-01", "holding_days": 5, "net_return_pct": 0.10},
        ]
    )

    result = simulate_portfolio(trades, config=OverlayConfig(max_concurrent=1))

    assert result.metrics["accepted_trades"] == 1
    assert result.metrics["skipped_trades"] == 1
    assert result.skipped_trades["skip_reason"].tolist() == ["max_concurrent"]


def test_o1_trend_filter_removes_entries_below_ma_or_negative_slope():
    trades = _trades(
        [
            {"stock_id": "A", "entry_date": "2024-01-02", "net_return_pct": 0.10},
            {"stock_id": "B", "entry_date": "2024-01-03", "net_return_pct": 0.10},
        ]
    )
    market = pd.DataFrame(
        [
            {"date": "2024-01-02", "close": 90.0, "ma_150": 100.0, "ma_150_slope": 1.0},
            {"date": "2024-01-03", "close": 110.0, "ma_150": 100.0, "ma_150_slope": -1.0},
        ]
    )

    result = simulate_portfolio(trades, config=OverlayConfig(max_concurrent=2, ma_long=150), market_trend=market)

    assert result.metrics["accepted_trades"] == 0
    assert result.skipped_trades["skip_reason"].tolist() == ["market_trend_ma_150", "market_trend_ma_150"]


def test_o2_drawdown_breaker_halts_and_resumes_new_entries():
    trades = _trades(
        [
            {"stock_id": "LOSS", "entry_date": "2024-01-01", "holding_days": 1, "net_return_pct": -0.30},
            {"stock_id": "RECOVERY_OPEN", "entry_date": "2024-01-01", "holding_days": 3, "net_return_pct": 0.40},
            {"stock_id": "HALTED", "entry_date": "2024-01-03", "holding_days": 1, "net_return_pct": 0.20},
            {"stock_id": "RESUMED", "entry_date": "2024-01-05", "holding_days": 1, "net_return_pct": 0.10},
        ]
    )

    result = simulate_portfolio(trades, config=OverlayConfig(max_concurrent=2, drawdown_halt=0.10))

    assert "drawdown_circuit" in result.skipped_trades["skip_reason"].tolist()
    assert "RESUMED" in result.accepted_trades["stock_id"].tolist()


def test_o3_regime_scaled_sizing_and_params_unchanged():
    original = load_params()
    trades = _trades(
        [
            {"stock_id": "ON", "entry_date": "2024-01-01", "net_return_pct": 0.10, "regime_bucket_at_entry": "risk_on"},
            {"stock_id": "OFF", "entry_date": "2024-01-03", "net_return_pct": 0.10, "regime_bucket_at_entry": "risk_off"},
            {"stock_id": "SEV", "entry_date": "2024-01-05", "net_return_pct": 0.10, "regime_bucket_at_entry": "severe"},
        ]
    )

    result = simulate_portfolio(trades, config=OverlayConfig(max_concurrent=1, regime_scaled=True))

    assert result.metrics["accepted_trades"] == 2
    assert result.metrics["skipped_trades"] == 1
    returns = result.accepted_trades.set_index("stock_id")["portfolio_return"].to_dict()
    assert returns["ON"] == pytest.approx(0.10)
    assert returns["OFF"] == pytest.approx(0.05)
    assert result.skipped_trades["skip_reason"].tolist() == ["regime_size_zero"]
    assert load_params() == original


def test_report_selects_candidate_without_2022_only_fitting():
    baseline = simulate_portfolio(_trades([{"stock_id": "A", "entry_date": "2024-01-01", "net_return_pct": -0.1}]), config=OverlayConfig(name="baseline"))
    improved = simulate_portfolio(_trades([{"stock_id": "A", "entry_date": "2024-01-01", "net_return_pct": 0.1}]), config=OverlayConfig(name="O2_DD_10"))
    report = build_overlay_report([baseline, improved])

    assert "comparison" in report
    assert "verdict" in report
