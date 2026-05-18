"""Configuration for Taiwan Multi-Factor Surge Screener v1.

Every threshold and weight here is a v1 hypothesis and requires backtesting.
"""

from __future__ import annotations

from typing import Any


RULE_SET_VERSION = "v1.0.0"
IS_V1_HYPOTHESIS = True
BACKTEST_REQUIRED = True


CONFIG: dict[str, Any] = {
    "rule_set_version": RULE_SET_VERSION,
    "is_v1_hypothesis": IS_V1_HYPOTHESIS,
    "backtest_required": BACKTEST_REQUIRED,
    "universe": {
        "default_scan_limit": 1000,  # backtest_required
        "max_scan_limit": 10000,  # backtest_required
        "allowed_markets": {"all", "twse", "tpex"},  # convention_required
        "twse_values": {"上市", "TWSE", "twse"},  # convention_required
        "tpex_values": {"上櫃", "TPEx", "TPEX", "otc", "tpex"},  # convention_required
        "excluded_market_values": {"興櫃", "emerging", "ETF"},  # convention_required
        "exclude_code_prefixes": ("00",),  # convention_required
        "warrant_prefixes": ("03", "04", "05", "06", "07", "08", "09"),  # convention_required
        "preferred_suffixes": ("A", "B"),  # convention_required
        "name_keywords": ("ETF", "ETN", "受益", "權證", "購", "售", "牛", "熊", "反1", "正2"),  # convention_required
        "industry_keywords": ("ETF", "fund", "基金", "權證"),  # convention_required
        "ky_name_suffix": "-KY",  # convention_required
        "ky_code_suffix": "KY",  # convention_required
    },
    "history": {
        "minimum_bars": 60,  # backtest_required
        "preferred_bars": 200,  # backtest_required
    },
    "liquidity": {
        "min_avg_volume_5d_lots": 500,  # backtest_required
        "min_avg_volume_5d_shares": 500_000,  # 500 lots * 1000 shares, backtest_required
        "lots_to_shares": 1000,  # convention_required
    },
    "fundamental": {
        "neutral_score": 50,  # backtest_required
        "high_score": 70,  # backtest_required
        "eps_yoy_good": 0.20,  # backtest_required
        "eps_yoy_strong": 0.40,  # backtest_required
        "roe_good": 0.12,  # backtest_required
        "roe_strong": 0.20,  # backtest_required
        "revenue_near_high_ratio": 0.95,  # backtest_required
        "eps_qoq_streak_good": 2,  # backtest_required
    },
    "chip": {
        "neutral_score": 50,  # backtest_required
        "high_score": 70,  # backtest_required
    },
    "technical": {
        "high_score": 70,  # backtest_required
        "kd_period": 9,  # backtest_required
        "kd_smooth_k": 3,  # backtest_required
        "kd_smooth_d": 3,  # backtest_required
        "kd_high_threshold": 80,  # backtest_required
        "kd_high_saturation_days": 3,  # backtest_required
        "macd_fast": 12,  # backtest_required
        "macd_slow": 26,  # backtest_required
        "macd_signal": 9,  # backtest_required
        "bb_period": 20,  # backtest_required
        "bb_std": 2,  # backtest_required
        "bb_squeeze_width_pct": 0.08,  # backtest_required
        "bb_expand_width_ratio": 1.2,  # backtest_required
        "obv_ma_period": 10,  # backtest_required
    },
    "sustain": {
        "high_score": 65,  # backtest_required
        "new_high_window": 200,  # backtest_required
        "new_high_count_days": 5,  # backtest_required
        "new_high_count_min": 3,  # backtest_required
        "volume_avg_days": 20,  # backtest_required
        "volume_surge_ratio": 1.4,  # backtest_required
        "volume_prev_day_ratio": 2.0,  # backtest_required
        "score_high_threshold": 55,  # backtest_required
    },
    "risk": {
        "overheat_score": 65,  # backtest_required
        "max_for_resonance": 60,  # backtest_required
        "upper_shadow_ratio": 0.5,  # backtest_required
        "upper_shadow_volume_ratio": 2.0,  # backtest_required
        "gap_up_pct": 0.05,  # backtest_required
        "gap_weak_close_position": 0.5,  # backtest_required
        "kd_extreme_threshold": 90,  # backtest_required
        "recent_overheat_return_5d": 0.15,  # backtest_required
    },
    "scoring": {
        "weights": {
            "fundamental_score": 0.20,  # backtest_required
            "chip_score": 0.25,  # backtest_required
            "technical_score": 0.25,  # backtest_required
            "breakout_sustain_score": 0.15,  # backtest_required
            "liquidity_score": 0.10,  # backtest_required
            "risk_score": -0.15,  # backtest_required
        },
    },
    "confidence": {
        "base": 100,  # backtest_required
        "chip_missing_penalty": 25,  # backtest_required
        "fundamental_all_missing_penalty": 30,  # backtest_required
        "fundamental_missing_each_penalty": 10,  # backtest_required
        "history_lt_200_penalty": 10,  # backtest_required
        "ohlcv_quality_penalty": 10,  # backtest_required
    },
    "classification": {
        "multi_factor_score_min": 75,  # backtest_required
        "multi_factor_modules_min": 3,  # backtest_required
        "module_high_score": 65,  # backtest_required
        "technical_initial_technical_min": 70,  # backtest_required
        "technical_initial_sustain_min": 55,  # backtest_required
        "chip_candidate_chip_min": 70,  # backtest_required
        "chip_candidate_liquidity_min": 60,  # backtest_required
        "chip_candidate_technical_min": 50,  # backtest_required
        "fundamental_candidate_fundamental_min": 70,  # backtest_required
        "fundamental_candidate_technical_min": 55,  # backtest_required
        "min_surge_score_default": 0,  # backtest_required
    },
}


def clamp_score(value: float) -> int:
    return max(0, min(100, int(round(value))))
