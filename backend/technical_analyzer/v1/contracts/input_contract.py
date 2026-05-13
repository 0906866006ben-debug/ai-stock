"""Input contracts for technical analyzer v1."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Literal, Optional

from ..common import pct_change


@dataclass(frozen=True)
class OHLCVBar:
    """One Taiwan equity bar using Decimal price precision."""

    date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    turnover_value: Decimal
    is_adjusted: bool
    data_source: str
    is_irregular_session: bool = False
    previous_close: Optional[Decimal] = None
    is_limit_up: bool = field(default=False, init=False)
    is_limit_down: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.low > self.high:
            raise ValueError("low cannot be greater than high")
        if self.volume < 0:
            raise ValueError("volume cannot be negative")
        if self.turnover_value < Decimal("0"):
            raise ValueError("turnover_value cannot be negative")
        if self.previous_close and self.previous_close > Decimal("0"):
            limit_pct = pct_change(self.close, self.previous_close)
            object.__setattr__(self, "is_limit_up", limit_pct is not None and limit_pct >= Decimal("9.9"))
            object.__setattr__(self, "is_limit_down", limit_pct is not None and limit_pct <= Decimal("-9.9"))


class OHLCVSeries:
    """Sorted OHLCV bars plus convenience helpers."""

    def __init__(self, symbol: str, bars: list[OHLCVBar]):
        if not bars:
            raise ValueError("bars must not be empty")
        if bars != sorted(bars, key=lambda bar: bar.date):
            raise ValueError("bars must be sorted ascending by date")
        self.symbol = symbol
        self.bars = bars
        self.max_gap_days = 0
        for earlier, later in zip(bars, bars[1:]):
            self.max_gap_days = max(self.max_gap_days, (later.date - earlier.date).days)

    def __len__(self) -> int:
        return len(self.bars)

    def __iter__(self):
        return iter(self.bars)

    def slice(self, n: int) -> "OHLCVSeries":
        return OHLCVSeries(self.symbol, self.bars[-n:])

    def latest(self) -> OHLCVBar:
        return self.bars[-1]

    def previous(self) -> Optional[OHLCVBar]:
        if len(self.bars) < 2:
            return None
        return self.bars[-2]

    def as_arrays(self) -> dict[str, list]:
        return {
            "date": [bar.date for bar in self.bars],
            "open": [bar.open for bar in self.bars],
            "high": [bar.high for bar in self.bars],
            "low": [bar.low for bar in self.bars],
            "close": [bar.close for bar in self.bars],
            "volume": [bar.volume for bar in self.bars],
            "turnover_value": [bar.turnover_value for bar in self.bars],
        }


@dataclass(frozen=True)
class ContextBundle:
    """Optional market and chip context used to de-bias confidence."""

    market_regime: Optional[Literal["bull", "bear", "neutral_volatile", "neutral_quiet"]] = None
    sector_strength: Optional[Literal["strong", "neutral", "weak"]] = None
    peer_confirmation: Optional[Literal["confirming", "neutral", "diverging"]] = None
    liquidity_bucket: Optional[Literal["high", "medium", "low", "illiquid"]] = None
    day_trading_noise_flag: Optional[bool] = None
    calendar_distortion_flag: Optional[bool] = None
    is_index_constituent: Optional[bool] = None
    market_cap_bucket: Optional[Literal["large", "mid", "small", "micro"]] = None
    day_trading_ratio: Optional[Decimal] = None
    foreign_net_buy_3d: Optional[Decimal] = None
    foreign_net_sell_3d: Optional[Decimal] = None
    foreign_net_buy_yesterday: Optional[Decimal] = None
    foreign_net_today: Optional[Decimal] = None
    foreign_net_buy_today: Optional[Decimal] = None
    trust_net_today: Optional[Decimal] = None
    dealer_net_today: Optional[Decimal] = None
    three_majors_net_today: Optional[Decimal] = None
    beta_60d: Optional[Decimal] = None
    margin_balance_change_pct_3d: Optional[Decimal] = None
    disposition_status: Optional[Literal["attention", "stage_1", "stage_2", "normal"]] = None
    is_ex_rights_today: Optional[bool] = None
    is_ex_rights_adjacent: Optional[bool] = None
    is_trading_suspended_today: Optional[bool] = None
    foreign_net_value_today: Optional[Decimal] = None
    trust_net_value_today: Optional[Decimal] = None
    dealer_net_value_today: Optional[Decimal] = None
    three_majors_net_value_today: Optional[Decimal] = None
    foreign_consecutive_days: Optional[int] = None
    trust_consecutive_days: Optional[int] = None
    dealer_consecutive_days: Optional[int] = None
    foreign_net_5d: Optional[Decimal] = None
    foreign_net_20d: Optional[Decimal] = None
    foreign_net_60d: Optional[Decimal] = None
    foreign_net_value_5d: Optional[Decimal] = None
    foreign_net_value_20d: Optional[Decimal] = None
    trust_net_5d: Optional[Decimal] = None
    trust_net_value_5d: Optional[Decimal] = None
    foreign_ownership_pct: Optional[Decimal] = None
    foreign_ownership_change_5d_pct: Optional[Decimal] = None
    trust_ownership_pct: Optional[Decimal] = None
    trust_ownership_change_5d_pct: Optional[Decimal] = None
    margin_balance: Optional[int] = None
    short_balance: Optional[int] = None
    short_balance_change_pct_3d: Optional[Decimal] = None
    short_to_long_ratio: Optional[Decimal] = None
    large_order_buy_ratio: Optional[Decimal] = None
    large_order_sell_ratio: Optional[Decimal] = None

    def completeness(self) -> Decimal:
        values = list(self.__dict__.values())
        populated = sum(1 for value in values if value is not None)
        return Decimal(populated) / Decimal(len(values))
