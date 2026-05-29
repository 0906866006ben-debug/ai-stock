import pandas as pd
import pytest

from backend.app.services.backtest.trade_simulator import TradeRules
from backend.app.services.backtest.v2.evaluator import apply_v2_entry_tiers, evaluate, metrics_from_trades, split_trade_rule_overrides
from backend.app.services.backtest.v2.walk_forward import Split


def _trades():
    return pd.DataFrame(
        [
            {
                "entry_status": "filled",
                "net_return_pct": 0.10,
                "hold_days": 5,
                "entry_tier": 4,
                "position_multiplier": 1.5,
                "candidate_type": "起漲前觀察",
                "sector_category": "cat1",
            },
            {
                "entry_status": "filled",
                "net_return_pct": -0.04,
                "hold_days": 8,
                "entry_tier": 2,
                "position_multiplier": 0.7,
                "candidate_type": "起漲前觀察",
                "sector_category": "cat2",
            },
            {
                "entry_status": "skipped_tier_below_min",
                "net_return_pct": None,
                "hold_days": 0,
                "entry_tier": 1,
                "position_multiplier": 0.3,
                "candidate_type": "起漲前觀察",
                "sector_category": "cat2",
            },
        ]
    )


def test_metrics_from_empty_trades_returns_zero():
    metrics = metrics_from_trades(pd.DataFrame())
    assert metrics.n_trades == 0
    assert metrics.win_rate == 0


def test_metrics_from_trades_computes_core_fields():
    metrics = metrics_from_trades(_trades())
    assert metrics.n_trades == 2
    assert metrics.win_rate == pytest.approx(0.5)
    assert metrics.net_return_pct == pytest.approx(0.06)
    assert metrics.profit_factor == pytest.approx(2.5)


def test_metrics_from_trades_keeps_tier_distribution():
    metrics = metrics_from_trades(_trades())
    assert metrics.tier_distribution == {4: 1, 2: 1}
    assert metrics.avg_position_multiplier == pytest.approx(1.1)


def test_metrics_from_trades_groups_all_sector_categories():
    metrics = metrics_from_trades(_trades())
    assert set(metrics.by_sector_category) == {"cat1", "cat2"}
    assert metrics.by_sector_category["cat1"]["n_trades"] == 1
    assert metrics.by_sector_category["cat2"]["n_trades"] == 1


def test_split_trade_rule_overrides_accepts_letter_tier():
    screener_params, rules = split_trade_rule_overrides(
        {
            "classification.pre_breakout_score_min": 55,
            "trade_rules.stop_loss_pct": 0.08,
            "trade_rules.min_entry_tier": "B",
        },
        TradeRules(),
    )
    assert screener_params == {"classification.pre_breakout_score_min": 55}
    assert rules.stop_loss_pct == pytest.approx(0.08)
    assert rules.min_entry_tier == 2


def test_evaluate_runs_each_split_with_injected_runner():
    splits = [
        Split("win_0_train", "2022-01-01", "2022-01-10", False, 0),
        Split("win_0_test", "2022-01-11", "2022-01-20", True, 0),
    ]
    calls = []

    def runner(split, rules, run_id):
        calls.append((split.name, rules.min_entry_tier, run_id))
        return _trades()

    result = evaluate(
        {"trade_rules.min_entry_tier": "A"},
        splits,
        universe=["2330"],
        segment_runner=runner,
        candidate_types=["起漲前觀察"],
    )
    assert set(result) == {"win_0_train", "win_0_test"}
    assert [call[0] for call in calls] == ["win_0_train", "win_0_test"]
    assert all(call[1] == 3 for call in calls)


def test_apply_v2_entry_tiers_reclassifies_signal_rows():
    signals = pd.DataFrame(
        [
            {
                "range_90d": 0.20,
                "volume_contraction_ratio": 0.8,
                "ema_spread": 0.04,
                "close_price": 101.0,
                "base_high": 100.0,
                "close_to_base_high_ratio": 1.01,
                "avg_turnover_20": 120_000_000,
                "return_90d": 0.08,
                "ema5_slope": 0.01,
                "ema10_slope": 0.005,
                "ema20_slope": 0.001,
                "base_range_pct": 0.12,
                "volume_today_shares": 150_000,
                "avg_volume_50": 100_000,
                "pre_breakout_score": 72,
                "ema_micro_upturn_score": 65,
                "base_compression_score": 63,
                "ema_down_to_up_transition_score": 55,
                "trend_template_ok": 1,
                "risk_score": 20,
                "entry_tier": 1,
            }
        ]
    )
    reclassified = apply_v2_entry_tiers(signals)
    assert int(reclassified.iloc[0]["entry_tier"]) == 4
