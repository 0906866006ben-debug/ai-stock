"""Pure candle psychology helpers."""

from __future__ import annotations

from decimal import Decimal

from ..common import ZERO, safe_div, quantize
from ..contracts.input_contract import OHLCVBar
from ..registry.rule_registry import RuleRegistry


def compute_candle_features(bar: OHLCVBar, registry: RuleRegistry | None = None) -> dict:
    """Compute pure candle geometry using Decimal arithmetic."""
    rules = RuleRegistry.load_default() if registry is None else registry
    thresholds = rules.section("candle_features")
    intraday_range = bar.high - bar.low
    body = abs(bar.close - bar.open)
    upper_shadow = bar.high - max(bar.open, bar.close)
    lower_shadow = min(bar.open, bar.close) - bar.low
    if intraday_range == ZERO:
        return {
            "intraday_range": intraday_range,
            "body": body,
            "upper_shadow": upper_shadow,
            "lower_shadow": lower_shadow,
            "upper_shadow_ratio": None,
            "lower_shadow_ratio": None,
            "body_ratio": None,
            "close_position_in_range": None,
            "is_doji": False,
            "is_marubozu_bullish": False,
            "is_marubozu_bearish": False,
            "is_long_upper_shadow": False,
            "is_long_lower_shadow": False,
            "is_metric_unavailable": True,
        }

    upper_shadow_ratio = safe_div(upper_shadow, intraday_range)
    lower_shadow_ratio = safe_div(lower_shadow, intraday_range)
    body_ratio = safe_div(body, intraday_range)
    close_position = safe_div(bar.close - bar.low, intraday_range)
    long_shadow_threshold = Decimal(str(thresholds["long_shadow_ratio_threshold"]))
    doji_threshold = Decimal(str(thresholds["doji_body_ratio_threshold"]))
    marubozu_threshold = Decimal(str(thresholds["marubozu_body_ratio_threshold"]))

    return {
        "intraday_range": quantize(intraday_range),
        "body": quantize(body),
        "upper_shadow": quantize(upper_shadow),
        "lower_shadow": quantize(lower_shadow),
        "upper_shadow_ratio": quantize(upper_shadow_ratio or ZERO),
        "lower_shadow_ratio": quantize(lower_shadow_ratio or ZERO),
        "body_ratio": quantize(body_ratio or ZERO),
        "close_position_in_range": quantize(close_position or ZERO),
        "is_doji": body_ratio is not None and body_ratio < doji_threshold,
        "is_marubozu_bullish": body_ratio is not None and body_ratio > marubozu_threshold and bar.close > bar.open,
        "is_marubozu_bearish": body_ratio is not None and body_ratio > marubozu_threshold and bar.close < bar.open,
        "is_long_upper_shadow": upper_shadow_ratio is not None and upper_shadow_ratio >= long_shadow_threshold,
        "is_long_lower_shadow": lower_shadow_ratio is not None and lower_shadow_ratio >= long_shadow_threshold,
        "is_metric_unavailable": False,
    }
