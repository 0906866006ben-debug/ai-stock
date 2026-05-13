"""Confirmed swing pivot detection."""

from __future__ import annotations

from decimal import Decimal

from ..contracts.enums import Horizon
from ..contracts.feature_contract import Pivot, SwingStructure
from ..contracts.input_contract import OHLCVSeries
from ..registry.rule_registry import RuleRegistry


def detect_swing_pivots(
    series: OHLCVSeries,
    lookback: int = 5,
) -> tuple[list[Pivot], list[Pivot], list[Pivot], list[Pivot]]:
    """Detect confirmed and currently unconfirmed pivots."""
    highs = [bar.high for bar in series.bars]
    lows = [bar.low for bar in series.bars]
    confirmed_highs: list[Pivot] = []
    confirmed_lows: list[Pivot] = []
    unconfirmed_highs: list[Pivot] = []
    unconfirmed_lows: list[Pivot] = []

    n = len(series.bars)
    for idx, bar in enumerate(series.bars):
        left = max(0, idx - lookback)
        right = min(n, idx + lookback + 1)
        if idx >= lookback and idx + lookback < n:
            if all(highs[idx] > highs[j] for j in range(idx - lookback, idx)) and all(
                highs[idx] > highs[j] for j in range(idx + 1, idx + lookback + 1)
            ):
                confirmed_highs.append(Pivot(date=bar.date, price=bar.high, pivot_type="high", index=idx))
            if all(lows[idx] < lows[j] for j in range(idx - lookback, idx)) and all(
                lows[idx] < lows[j] for j in range(idx + 1, idx + lookback + 1)
            ):
                confirmed_lows.append(Pivot(date=bar.date, price=bar.low, pivot_type="low", index=idx))
            continue

        if idx >= lookback:
            if highs[idx] == max(highs[left:right]):
                unconfirmed_highs.append(
                    Pivot(date=bar.date, price=bar.high, pivot_type="high", index=idx, confirmed=False)
                )
            if lows[idx] == min(lows[left:right]):
                unconfirmed_lows.append(
                    Pivot(date=bar.date, price=bar.low, pivot_type="low", index=idx, confirmed=False)
                )

    return confirmed_highs, confirmed_lows, unconfirmed_highs, unconfirmed_lows


def infer_swing_structure(
    series: OHLCVSeries,
    horizon: Horizon,
    registry: RuleRegistry | None = None,
) -> SwingStructure:
    """Infer higher-high / lower-low structure from confirmed pivots."""
    rules = RuleRegistry.load_default() if registry is None else registry
    lookback = int(rules.thresholds_for(horizon)["swing_pivot_lookback"])
    highs, lows, unconfirmed_highs, unconfirmed_lows = detect_swing_pivots(series, lookback=lookback)
    bos_up = False
    bos_down = False
    if len(highs) >= 2 and highs[-1].price > highs[-2].price:
        bos_up = True
    if len(lows) >= 2 and lows[-1].price < lows[-2].price:
        bos_down = True
    return SwingStructure(
        swing_highs=tuple(highs),
        swing_lows=tuple(lows),
        unconfirmed_highs=tuple(unconfirmed_highs),
        unconfirmed_lows=tuple(unconfirmed_lows),
        bos_up=bos_up,
        bos_down=bos_down,
    )
