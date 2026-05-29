from __future__ import annotations

from pathlib import Path

import pandas as pd

from backend.app.services.backtest.trade_simulator import TradeRules, load_trades, simulate_trades
from backend.app.services.screener_rules import load_surge_candidate_rules
from backend.app.services.screener_service import _compute_base_features, _compute_entry_tier


def _base_features(**overrides) -> dict:
    features = {
        "range_90d": 0.20,
        "volume_contraction_ratio": 0.80,
        "ema_spread": 0.06,
        "base_high": 100.0,
        "close_today": 100.2,
        "close_to_base_high_ratio": 1.002,
        "avg_turnover_20": 50_000_000.0,
        "return_90d": 0.12,
        "ema5_slope": -0.01,
        "ema10_slope": -0.01,
        "ema20_slope": -0.01,
        "base_range_pct": 0.18,
        "volume_today_shares": 1_000_000.0,
        "avg_volume_50_shares": 1_000_000.0,
        "pre_breakout_score": 45,
        "ema_micro_upturn_score": 35,
        "base_compression_score": 45,
        "ema_down_to_up_transition_score": 30,
        "trend_template_ok": False,
    }
    features.update(overrides)
    return features


def test_entry_tier_zero_when_basic_gates_fail():
    rules = load_surge_candidate_rules()
    features = _base_features(range_90d=0.35)

    assert _compute_entry_tier(features, rules, risk_score=40) == 0


def test_entry_tier_one_for_basic_breakout():
    rules = load_surge_candidate_rules()

    assert _compute_entry_tier(_base_features(), rules, risk_score=40) == 1


def test_entry_tier_two_with_quality_filters():
    rules = load_surge_candidate_rules()
    features = _base_features(
        ema_spread=0.04,
        ema5_slope=0.001,
        ema10_slope=0.001,
        ema20_slope=0.001,
        base_range_pct=0.14,
        volume_today_shares=1_250_000.0,
        pre_breakout_score=55,
        ema_micro_upturn_score=45,
    )

    assert _compute_entry_tier(features, rules, risk_score=40) == 2


def test_entry_tier_three_premium():
    rules = load_surge_candidate_rules()
    features = _base_features(
        ema_spread=0.04,
        ema5_slope=0.001,
        ema10_slope=0.001,
        ema20_slope=0.001,
        base_range_pct=0.12,
        volume_today_shares=1_600_000.0,
        pre_breakout_score=65,
        ema_micro_upturn_score=65,
        base_compression_score=65,
        ema_down_to_up_transition_score=55,
        avg_turnover_20=120_000_000.0,
        trend_template_ok=True,
    )

    assert _compute_entry_tier(features, rules, risk_score=40) == 3


def _trend_frame(days: int) -> pd.DataFrame:
    rows = []
    for i in range(days):
        close = 80.0 + i * 0.25
        rows.append({
            "open": close * 0.995,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": 1_000_000,
            "turnover_value": close * 1_000_000,
        })
    return pd.DataFrame(rows)


def test_trend_template_ok_requires_200_bars():
    rules = load_surge_candidate_rules()
    short = _compute_base_features(
        _trend_frame(150),
        None,
        rules,
        data_quality_flags=[],
        missing_data=[],
    )
    long = _compute_base_features(
        _trend_frame(220),
        None,
        rules,
        data_quality_flags=[],
        missing_data=[],
    )

    assert short["trend_template_ok"] is False
    assert long["trend_template_ok"] is True


class _FakeStore:
    def get_ohlcv(self, stock_id: str, start_date: str, end_date: str) -> pd.DataFrame:
        return pd.DataFrame([
            {"date": "2024-01-02", "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 1_000_000},
            {"date": "2024-01-03", "open": 100.0, "high": 111.0, "low": 99.0, "close": 110.0, "volume": 1_000_000},
        ])


def test_tier_position_multiplier_in_simulator(tmp_path: Path):
    signals = pd.DataFrame([
        {"run_id": "tier", "signal_date": "2024-01-01", "stock_id": "AAA", "candidate_type": "起漲前觀察", "close_price": 100.0, "entry_tier": 1},
        {"run_id": "tier", "signal_date": "2024-01-01", "stock_id": "BBB", "candidate_type": "起漲前觀察", "close_price": 100.0, "entry_tier": 2},
        {"run_id": "tier", "signal_date": "2024-01-01", "stock_id": "CCC", "candidate_type": "起漲前觀察", "close_price": 100.0, "entry_tier": 3},
    ])
    rules = TradeRules(
        measured_move_method="fixed",
        target_pct=0.10,
        commission_pct=0.0,
        transaction_tax_pct=0.0,
        slippage_pct=0.0,
    )

    simulate_trades(signals_df=signals, data_store=_FakeStore(), rules=rules, run_id="tier", db_path=tmp_path / "tier.db")
    trades = load_trades(tmp_path / "tier.db", "tier").sort_values("entry_tier")

    assert trades["net_return_pct"].tolist() == [0.05, 0.10, 0.15]
    assert trades["position_multiplier"].tolist() == [0.5, 1.0, 1.5]
