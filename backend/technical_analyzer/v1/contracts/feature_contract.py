"""Feature bundle contracts for technical analyzer v1."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

from .enums import Horizon, TechnicalState
from .input_contract import OHLCVSeries


@dataclass(frozen=True)
class Pivot:
    """Confirmed pivot produced by swing structure logic."""

    date: date
    price: Decimal
    pivot_type: str
    index: int
    confirmed: bool = True


@dataclass(frozen=True)
class SwingStructure:
    """Minimal swing structure contract shared across feature modules."""

    swing_highs: tuple[Pivot, ...] = ()
    swing_lows: tuple[Pivot, ...] = ()
    unconfirmed_highs: tuple[Pivot, ...] = ()
    unconfirmed_lows: tuple[Pivot, ...] = ()
    bos_up: bool = False
    bos_down: bool = False

    @property
    def last_two_highs(self) -> tuple[Pivot, ...]:
        return self.swing_highs[-2:]

    @property
    def last_two_lows(self) -> tuple[Pivot, ...]:
        return self.swing_lows[-2:]


@dataclass(frozen=True)
class FeatureBundle:
    """Analyzer-ready feature snapshot for one horizon."""

    series: OHLCVSeries
    horizon: Horizon
    current_state: TechnicalState = TechnicalState.MIXED_SIGNALS
    ma_values: dict[str, Decimal] = field(default_factory=dict)
    ma_slopes_pct: dict[str, Decimal] = field(default_factory=dict)
    close_crosses_ma20_20d: int = 0
    volume_ratio_20d: Optional[Decimal] = None
    volume_ratio_5d: Optional[Decimal] = None
    volume_median_up_days_5: Optional[Decimal] = None
    volume_median_down_days_5: Optional[Decimal] = None
    turnover_value_ratio_20d: Optional[Decimal] = None
    turnover_value_5d_avg: Optional[Decimal] = None
    turnover_value_20d_avg: Optional[Decimal] = None
    deviation_from_ma20_pct: Optional[Decimal] = None
    deviation_from_ma60_pct: Optional[Decimal] = None
    atr_value: Optional[Decimal] = None
    atr_series: tuple[Optional[Decimal], ...] = ()
    atr_ratio_percentile_60d: Optional[Decimal] = None
    bias_20_pct: Optional[Decimal] = None
    bias_20_series: tuple[Decimal, ...] = ()
    bias_20_percentile_1y: Optional[Decimal] = None
    rsi_series: tuple[Optional[Decimal], ...] = ()
    macd_line: tuple[Optional[Decimal], ...] = ()
    macd_signal: tuple[Optional[Decimal], ...] = ()
    macd_histogram: tuple[Optional[Decimal], ...] = ()
    kd_k: tuple[Optional[Decimal], ...] = ()
    kd_d: tuple[Optional[Decimal], ...] = ()
    bollinger_upper: tuple[Optional[Decimal], ...] = ()
    bollinger_middle: tuple[Optional[Decimal], ...] = ()
    bollinger_lower: tuple[Optional[Decimal], ...] = ()
    bollinger_bandwidth_series: tuple[Optional[Decimal], ...] = ()
    swing_structure: Optional[SwingStructure] = None
    recent_high_5d: Optional[Decimal] = None
    recent_low_5d: Optional[Decimal] = None
    recent_high_20d: Optional[Decimal] = None
    recent_low_20d: Optional[Decimal] = None
    recent_high_60d: Optional[Decimal] = None
    recent_low_60d: Optional[Decimal] = None
    consecutive_down_closes_5d: int = 0

    def latest_close(self) -> Decimal:
        return self.series.latest().close

    def latest_value(self, name: str) -> Optional[Decimal]:
        mapping = {
            "rsi": self.rsi_series,
            "macd": self.macd_line,
            "macd_signal": self.macd_signal,
            "macd_histogram": self.macd_histogram,
            "kd_k": self.kd_k,
            "kd_d": self.kd_d,
            "bb_upper": self.bollinger_upper,
            "bb_middle": self.bollinger_middle,
            "bb_lower": self.bollinger_lower,
        }
        series = mapping.get(name)
        if not series:
            return None
        for value in reversed(series):
            if value is not None:
                return value
        return None
