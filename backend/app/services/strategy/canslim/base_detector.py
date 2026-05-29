"""Standalone CAN SLIM base geometry detector.

The existing ``screener_service`` base logic is a simple box/compression signal
inside the older surge classifier: it looks at windows such as ``close[-60:-19]``
or recent 20/30/40-bar boxes and contributes to that classifier's scores. This
module is intentionally separate and does not import that logic. It implements a
CAN SLIM-oriented cup-and-handle / flat-base geometry detector from the YAML
thresholds, returning a graded quality score for future aggregation.

Open question for a later phase: whether these two base concepts should be
unified. For Phase D they remain complementary and standalone.
"""
from __future__ import annotations

from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field


class BasePattern(BaseModel):
    model_config = ConfigDict(frozen=True)

    pattern_type: Literal["cup_and_handle", "flat_base", "none"]
    cup_depth: float | None = None
    handle_pullback: float | None = None
    handle_in_upper_half: bool | None = None
    base_length_weeks: float | None = None
    handle_volume_dryup: float | None = None
    breakout_confirmed: bool | None = None
    pivot_price: float | None = None
    quality_score: int = 0
    missing_fields: list[str] = Field(default_factory=list)
    data_warnings: list[str] = Field(default_factory=list)


def detect_base(bars: pd.DataFrame, params: dict[str, Any]) -> BasePattern:
    """Detect CAN SLIM base geometry from chronological OHLCV bars."""
    thresholds = params["base_geometry"]
    cup_cfg = thresholds["cup_and_handle"]
    min_bars = int(float(cup_cfg["base_length_min_weeks"]) * 5)
    if len(bars) < min_bars:
        return BasePattern(
            pattern_type="none",
            base_length_weeks=len(bars) / 5 if len(bars) else 0.0,
            quality_score=0,
            missing_fields=["base_length_weeks"],
            data_warnings=["insufficient bars for base geometry detection"],
        )

    cleaned = _clean_bars(bars)
    if cleaned is None:
        return BasePattern(
            pattern_type="none",
            quality_score=0,
            missing_fields=["open/high/low/close/volume"],
            data_warnings=["bars missing required OHLCV columns"],
        )

    cup = _detect_cup_and_handle(cleaned, thresholds)
    if cup is not None:
        return cup

    flat = _detect_flat_base(cleaned, thresholds)
    if flat is not None:
        return flat

    return BasePattern(pattern_type="none", base_length_weeks=len(cleaned) / 5, quality_score=0)


def _detect_cup_and_handle(bars: pd.DataFrame, thresholds: dict[str, Any]) -> BasePattern | None:
    cfg = thresholds["cup_and_handle"]
    closes = bars["close"].reset_index(drop=True)
    volumes = bars["volume"].reset_index(drop=True)
    n = len(bars)
    first_third_end = max(1, n // 3)
    left_peak_idx = int(closes.iloc[:first_third_end].idxmax())
    if left_peak_idx >= n - 3:
        return None

    bottom_region_end = max(left_peak_idx + 2, n - max(3, n // 5))
    if bottom_region_end <= left_peak_idx + 1:
        return None
    bottom_idx = int(closes.iloc[left_peak_idx + 1 : bottom_region_end].idxmin())
    if bottom_idx >= n - 3:
        return None

    right_region = closes.iloc[bottom_idx + 1 : n - 1]
    if right_region.empty:
        return None
    right_peak_idx = int(right_region.idxmax())
    if right_peak_idx >= n - 1:
        return None

    left_peak = float(closes.iloc[left_peak_idx])
    bottom = float(closes.iloc[bottom_idx])
    right_peak = float(closes.iloc[right_peak_idx])
    if left_peak <= 0 or right_peak <= 0:
        return None

    cup_depth = (left_peak - bottom) / left_peak
    valid_cup = float(cfg["cup_depth_min"]) <= cup_depth <= float(cfg["cup_depth_max"])
    if not valid_cup:
        return None

    handle_closes = closes.iloc[right_peak_idx + 1 : n - 1]
    handle_volumes = volumes.iloc[right_peak_idx + 1 : n - 1]
    if handle_closes.empty or handle_volumes.empty:
        return BasePattern(
            pattern_type="cup_and_handle",
            cup_depth=cup_depth,
            base_length_weeks=n / 5,
            pivot_price=right_peak,
            breakout_confirmed=False,
            quality_score=60,
            data_warnings=["handle region missing"],
        )

    handle_low = float(handle_closes.min())
    handle_pullback = (right_peak - handle_low) / right_peak
    upper_half_floor = bottom + (left_peak - bottom) / 2
    handle_in_upper_half = handle_low >= upper_half_floor
    handle_valid = handle_pullback <= float(cfg["handle_pullback_max_upper"]) and handle_in_upper_half

    cup_volumes = volumes.iloc[left_peak_idx : right_peak_idx + 1]
    handle_mean_volume = float(handle_volumes.mean())
    cup_mean_volume = float(cup_volumes.mean())
    handle_volume_dryup = 1 - handle_mean_volume / cup_mean_volume if cup_mean_volume else None
    volume_dryup_met = handle_volume_dryup is not None and handle_volume_dryup >= float(cfg["handle_volume_dryup_min"])

    breakout_confirmed = (
        float(closes.iloc[-1]) > right_peak
        and handle_mean_volume > 0
        and float(volumes.iloc[-1]) >= handle_mean_volume * (1 + float(cfg["breakout_volume_increase_min"]))
    )

    score = 40 + 20
    if handle_valid:
        score += 15
    if volume_dryup_met:
        score += 15
    if breakout_confirmed:
        score += 10

    return BasePattern(
        pattern_type="cup_and_handle",
        cup_depth=cup_depth,
        handle_pullback=handle_pullback,
        handle_in_upper_half=handle_in_upper_half,
        base_length_weeks=n / 5,
        handle_volume_dryup=handle_volume_dryup,
        breakout_confirmed=breakout_confirmed,
        pivot_price=right_peak,
        quality_score=min(score, 100),
    )


def _detect_flat_base(bars: pd.DataFrame, thresholds: dict[str, Any]) -> BasePattern | None:
    cfg = thresholds["flat_base"]
    high = float(bars["high"].max())
    low = float(bars["low"].min())
    if low <= 0:
        return None
    box_range_pct = (high - low) / low
    if box_range_pct > float(cfg["box_range_pct_max"]):
        return None

    close = float(bars["close"].iloc[-1])
    breakout_confirmed = close > high * float(cfg["breakout_multiplier"])
    score = 40 + 20 + (10 if breakout_confirmed else 0)
    return BasePattern(
        pattern_type="flat_base",
        base_length_weeks=len(bars) / 5,
        breakout_confirmed=breakout_confirmed,
        pivot_price=high,
        quality_score=min(score, 100),
    )


def _clean_bars(bars: pd.DataFrame) -> pd.DataFrame | None:
    required = {"open", "high", "low", "close", "volume"}
    if not required.issubset(bars.columns):
        return None
    cleaned = bars.copy()
    for column in required:
        cleaned[column] = pd.to_numeric(cleaned[column], errors="coerce")
    cleaned = cleaned.dropna(subset=list(required))
    return cleaned if not cleaned.empty else None
