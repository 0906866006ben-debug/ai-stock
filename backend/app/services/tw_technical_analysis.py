"""
Taiwan stock technical analysis using pandas/numpy.
Computes MA, RSI, MACD, and volume statistics.
"""
import pandas as pd
import numpy as np
from typing import Optional


def compute_moving_averages(closes: list[float]) -> dict:
    """Compute MA5, MA20, MA60."""
    if not closes:
        return {"ma5": None, "ma20": None, "ma60": None}

    s = pd.Series(closes)
    return {
        "ma5": round(float(s.rolling(5).mean().iloc[-1]), 2) if len(closes) >= 5 else None,
        "ma20": round(float(s.rolling(20).mean().iloc[-1]), 2) if len(closes) >= 20 else None,
        "ma60": round(float(s.rolling(60).mean().iloc[-1]), 2) if len(closes) >= 60 else None,
    }


def compute_rsi(closes: list[float], period: int = 14) -> Optional[float]:
    """Compute RSI(14)."""
    if not closes or len(closes) < period + 1:
        return None

    s = pd.Series(closes)
    delta = s.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))

    result = rsi.iloc[-1]
    return round(float(result), 2) if not pd.isna(result) else None


def compute_macd(closes: list[float]) -> Optional[dict]:
    """Compute MACD(12, 26, 9) with signal line and histogram."""
    if not closes or len(closes) < 26:
        return None

    s = pd.Series(closes)
    ema12 = s.ewm(span=12).mean()
    ema26 = s.ewm(span=26).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9).mean()
    histogram = macd_line - signal_line

    return {
        "macd": round(float(macd_line.iloc[-1]), 4),
        "signal": round(float(signal_line.iloc[-1]), 4),
        "histogram": round(float(histogram.iloc[-1]), 4),
    }


def compute_volume_stats(volumes: list[int]) -> dict:
    """Compute volume statistics."""
    if not volumes:
        return {"avg_vol_20": None, "latest_vol": None, "vol_ratio": None}

    v = pd.Series(volumes)
    avg_20 = v.tail(20).mean() if len(volumes) >= 20 else v.mean()
    latest = volumes[-1]
    ratio = latest / avg_20 if avg_20 > 0 else 0

    return {
        "avg_vol_20": int(avg_20),
        "latest_vol": latest,
        "vol_ratio": round(ratio, 2),
    }


def compute_price_changes(closes: list[float]) -> dict:
    """Compute price changes over different periods."""
    if not closes:
        return {"change_5d": None, "change_20d": None, "change_60d": None}

    current = closes[-1]

    change_5d = None
    if len(closes) >= 5:
        change_5d = round((current - closes[-5]) / closes[-5] * 100, 2)

    change_20d = None
    if len(closes) >= 20:
        change_20d = round((current - closes[-20]) / closes[-20] * 100, 2)

    change_60d = None
    if len(closes) >= 60:
        change_60d = round((current - closes[-60]) / closes[-60] * 100, 2)

    return {
        "change_5d": change_5d,
        "change_20d": change_20d,
        "change_60d": change_60d,
    }


def compute_all_indicators(candles: list[dict]) -> dict:
    """Compute all technical indicators from OHLCV candles."""
    if not candles:
        return {
            "ma": {"ma5": None, "ma20": None, "ma60": None},
            "rsi": None,
            "macd": None,
            "volume": {"avg_vol_20": None, "latest_vol": None, "vol_ratio": None},
            "price_changes": {"change_5d": None, "change_20d": None, "change_60d": None},
        }

    closes = [c["close"] for c in candles]
    volumes = [c["volume"] for c in candles]

    return {
        "ma": compute_moving_averages(closes),
        "rsi": compute_rsi(closes),
        "macd": compute_macd(closes),
        "volume": compute_volume_stats(volumes),
        "price_changes": compute_price_changes(closes),
    }
