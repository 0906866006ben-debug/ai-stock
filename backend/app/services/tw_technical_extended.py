"""
Extended technical analysis indicators for Taiwan stocks.

Adds:
- KD (Stochastic) indicator
- Bollinger Bands
- ATR (Average True Range)
- Support/Resistance levels
- Breakout detection
- Trend direction
"""
from __future__ import annotations
from backend.app.services.tw_indicators import sma


def kd_indicator(
    highs: list[float], lows: list[float], closes: list[float], period: int = 9, smooth_k: int = 3, smooth_d: int = 3
) -> dict[str, list[float | None]]:
    """
    Calculate KD (Stochastic) indicator.

    Returns: {"%K": [...], "%D": [...]}
    """
    n = len(closes)
    out_k: list[float | None] = [None] * n
    out_d: list[float | None] = [None] * n

    if n < period:
        return {"%K": out_k, "%D": out_d}

    # Calculate raw %K
    raw_k: list[float | None] = [None] * n
    for i in range(period - 1, n):
        window_high = max(highs[i - period + 1 : i + 1])
        window_low = min(lows[i - period + 1 : i + 1])
        range_hl = window_high - window_low

        if range_hl == 0:
            raw_k[i] = 50.0
        else:
            raw_k[i] = 100.0 * (closes[i] - window_low) / range_hl

    # Smooth %K
    raw_k_values = [x for x in raw_k if x is not None]
    if len(raw_k_values) >= smooth_k:
        smoothed_k = sma(raw_k_values, smooth_k)
        j = 0
        for i in range(n):
            if raw_k[i] is not None:
                if j < len(smoothed_k) and smoothed_k[j] is not None:
                    out_k[i] = smoothed_k[j]
                j += 1

    # Smooth to get %D
    k_values = [x for x in out_k if x is not None]
    if len(k_values) >= smooth_d:
        smoothed_d = sma(k_values, smooth_d)
        j = 0
        for i in range(n):
            if out_k[i] is not None:
                if j < len(smoothed_d) and smoothed_d[j] is not None:
                    out_d[i] = smoothed_d[j]
                j += 1

    return {"%K": out_k, "%D": out_d}


def bollinger_bands(
    closes: list[float], period: int = 20, std_dev: float = 2.0
) -> dict[str, list[float | None]]:
    """
    Calculate Bollinger Bands.

    Returns: {
        "upper": [...],
        "middle": [...],
        "lower": [...],
    }
    """
    n = len(closes)
    middle = sma(closes, period)
    upper: list[float | None] = [None] * n
    lower: list[float | None] = [None] * n

    for i in range(n):
        if middle[i] is None:
            continue

        if i < period - 1:
            continue

        window = closes[i - period + 1 : i + 1]
        variance = sum((x - middle[i]) ** 2 for x in window) / period
        std = variance ** 0.5

        upper[i] = middle[i] + (std_dev * std)
        lower[i] = middle[i] - (std_dev * std)

    return {"upper": upper, "middle": middle, "lower": lower}


def atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> list[float | None]:
    """
    Calculate ATR (Average True Range).

    ATR measures volatility based on true range.
    """
    n = len(closes)
    tr: list[float] = []

    # Calculate true ranges
    for i in range(n):
        high = highs[i]
        low = lows[i]
        close_prev = closes[i - 1] if i > 0 else closes[i]

        tr1 = high - low
        tr2 = abs(high - close_prev)
        tr3 = abs(low - close_prev)

        tr.append(max(tr1, tr2, tr3))

    # Average true range
    atr_values: list[float | None] = [None] * n

    if n < period:
        return atr_values

    # First ATR is simple average
    atr_values[period - 1] = sum(tr[:period]) / period

    # Subsequent ATRs use smoothing
    for i in range(period, n):
        atr_values[i] = (atr_values[i - 1] * (period - 1) + tr[i]) / period

    return atr_values


def support_resistance(highs: list[float], lows: list[float], period: int = 20) -> dict[str, list[float]]:
    """
    Detect support and resistance levels.

    Returns: {
        "support": [level1, level2, ...],
        "resistance": [level1, level2, ...]
    }
    """
    n = len(highs)
    support_levels: list[float] = []
    resistance_levels: list[float] = []

    if n < period:
        return {"support": support_levels, "resistance": resistance_levels}

    # Find local lows (support) and highs (resistance)
    for i in range(period // 2, n - period // 2):
        window_lows = lows[i - period // 2 : i + period // 2 + 1]
        window_highs = highs[i - period // 2 : i + period // 2 + 1]

        local_low = min(window_lows)
        local_high = max(window_highs)

        if lows[i] == local_low and lows[i] not in support_levels:
            support_levels.append(lows[i])

        if highs[i] == local_high and highs[i] not in resistance_levels:
            resistance_levels.append(highs[i])

    # Sort and keep top 3
    support_levels = sorted(set(support_levels), reverse=True)[:3]
    resistance_levels = sorted(set(resistance_levels), reverse=True)[:3]

    return {"support": support_levels, "resistance": resistance_levels}


def trend_direction(highs: list[float], lows: list[float], period: int = 20) -> str:
    """
    Determine trend direction: uptrend, downtrend, or sideways.

    Uptrend: higher highs and higher lows
    Downtrend: lower highs and lower lows
    Sideways: neither
    """
    n = len(highs)
    if n < period:
        return "sideways"

    # Compare recent highs/lows with older ones
    recent_high = max(highs[-period:])
    recent_low = min(lows[-period:])
    prev_high = max(highs[-2 * period : -period])
    prev_low = min(lows[-2 * period : -period])

    if recent_high > prev_high and recent_low > prev_low:
        return "uptrend"
    elif recent_high < prev_high and recent_low < prev_low:
        return "downtrend"
    else:
        return "sideways"


def breakout_detection(
    closes: list[float], resistance_level: float, support_level: float
) -> dict[str, bool | str]:
    """
    Detect if price is breaking out above resistance or below support.

    Returns: {
        "breakout_direction": "upside" | "downside" | "none",
        "above_resistance": bool,
        "below_support": bool,
    }
    """
    if not closes:
        return {"breakout_direction": "none", "above_resistance": False, "below_support": False}

    current_price = closes[-1]
    prev_price = closes[-2] if len(closes) > 1 else current_price

    above_resistance = current_price > resistance_level and prev_price <= resistance_level
    below_support = current_price < support_level and prev_price >= support_level

    direction = "upside" if above_resistance else ("downside" if below_support else "none")

    return {
        "breakout_direction": direction,
        "above_resistance": current_price > resistance_level,
        "below_support": current_price < support_level,
    }


def compute_extended_indicators(candles: list[dict]) -> dict:
    """
    Compute all extended technical indicators from OHLCV candles.

    Candle format: {"time": "...", "open": ..., "high": ..., "low": ..., "close": ..., "volume": ...}

    Returns: {
        "ma120": [...],
        "ma240": [...],
        "kd": {"%K": [...], "%D": [...]},
        "bollinger_bands": {"upper": [...], "middle": [...], "lower": [...]},
        "atr": [...],
        "support": [level1, level2, level3],
        "resistance": [level1, level2, level3],
        "trend": "uptrend|downtrend|sideways",
        "breakout": {...},
    }
    """
    if not candles:
        return {
            "ma120": [],
            "ma240": [],
            "kd": {"%K": [], "%D": []},
            "bollinger_bands": {"upper": [], "middle": [], "lower": []},
            "atr": [],
            "support": [],
            "resistance": [],
            "trend": "sideways",
            "breakout": {"breakout_direction": "none", "above_resistance": False, "below_support": False},
        }

    closes = [float(c["close"]) for c in candles]
    highs = [float(c["high"]) for c in candles]
    lows = [float(c["low"]) for c in candles]

    # Compute all indicators
    ma120 = sma(closes, 120)
    ma240 = sma(closes, 240)
    kd = kd_indicator(highs, lows, closes)
    bb = bollinger_bands(closes)
    atr_vals = atr(highs, lows, closes)
    sr = support_resistance(highs, lows)
    trend = trend_direction(highs, lows)

    # Get resistance/support for breakout detection
    resistance = sr["resistance"][0] if sr["resistance"] else max(highs[-20:])
    support = sr["support"][0] if sr["support"] else min(lows[-20:])
    breakout = breakout_detection(closes, resistance, support)

    return {
        "ma120": ma120,
        "ma240": ma240,
        "kd": kd,
        "bollinger_bands": bb,
        "atr": atr_vals,
        "support": sr["support"],
        "resistance": sr["resistance"],
        "trend": trend,
        "breakout": breakout,
    }
