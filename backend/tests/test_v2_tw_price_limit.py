import pandas as pd
import pytest

from backend.app.services.backtest.trade_simulator import ExitReason, TradeRules, _signal_entry_tier, _walk_until_exit


def test_legacy_stop_loss_still_fills_at_stop_price():
    bars = pd.DataFrame(
        [
            {"date": "2024-01-02", "open": 90.0, "high": 90.0, "low": 90.0, "close": 90.0},
            {"date": "2024-01-03", "open": 85.0, "high": 88.0, "low": 84.0, "close": 86.0},
        ]
    )
    exit_date, exit_price, reason, hold_days = _walk_until_exit(
        bars,
        100.0,
        TradeRules(stop_loss_pct=0.10, include_tw_price_limit=False),
        previous_close=100.0,
    )
    assert exit_date == "2024-01-02"
    assert exit_price == 90.0
    assert reason == ExitReason.STOP_LOSS.value
    assert hold_days == 1


def test_v2_limit_down_stop_fills_next_tradable_open():
    bars = pd.DataFrame(
        [
            {"date": "2024-01-02", "open": 90.0, "high": 90.0, "low": 90.0, "close": 90.0},
            {"date": "2024-01-03", "open": 85.0, "high": 88.0, "low": 84.0, "close": 86.0},
        ]
    )
    exit_date, exit_price, reason, hold_days = _walk_until_exit(
        bars,
        100.0,
        TradeRules(stop_loss_pct=0.10, include_tw_price_limit=True),
        previous_close=100.0,
    )
    assert exit_date == "2024-01-03"
    assert exit_price == 85.0
    assert reason == ExitReason.STOP_LOSS_LIMIT_DOWN_NEXT_OPEN.value
    assert hold_days == 2


def test_target_reached_unchanged_by_price_limit_flag():
    bars = pd.DataFrame(
        [{"date": "2024-01-02", "open": 101.0, "high": 116.0, "low": 100.0, "close": 114.0}]
    )
    _date, exit_price, reason, _days = _walk_until_exit(
        bars,
        100.0,
        TradeRules(target_pct=0.15, include_tw_price_limit=True),
        previous_close=100.0,
    )
    assert exit_price == pytest.approx(115.0)
    assert reason == ExitReason.TARGET_REACHED.value


def test_signal_entry_tier_accepts_v2_s_tier():
    assert _signal_entry_tier({"entry_tier": 4}) == 4
