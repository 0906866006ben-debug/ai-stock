"""Point-in-time CAN SLIM tradable universe builder.

Candidate symbols may come from `universe_source.get_tech_universe_symbols()`,
which is based on the current free FinMind TaiwanStockInfo list — that source
excludes already-delisted securities. To remove the resulting survivorship bias,
callers can merge `universe_source.get_delisted_universe_symbols()` into the
candidate pool (with their OHLCV backfilled) and pass `max_staleness_days` so a
delisted name leaves the universe on the date it stops trading. Membership stays
PIT-safe either way: only OHLCV bars on or before `as_of_date` are inspected.
"""
from __future__ import annotations

from typing import Iterable

import pandas as pd

from backend.app.services.strategy.canslim.params import load_params
from backend.app.services.strategy.canslim.universe_source import get_tech_universe_symbols


def get_universe_as_of(
    as_of_date: str,
    store,
    *,
    turnover_floor: float | None = None,
    candidate_symbols: Iterable[str] | None = None,
    min_history_bars: int = 60,
    liquidity_lookback_bars: int = 20,
    max_staleness_days: int | None = None,
) -> list[str]:
    """Return symbols liquid enough as of `as_of_date`, using no future data.

    When `max_staleness_days` is set, a symbol whose most recent bar on/before
    `as_of_date` is older than that many calendar days is dropped. This is the
    mechanism that makes a delisted name fall out of the universe once it stops
    trading: `get_ohlcv_as_of` otherwise happily returns its last (stale) bars
    forever, which would re-introduce the survivorship bias we are removing. Left
    as None it is a no-op, so existing validated runs are unaffected.
    """
    floor = _turnover_floor(turnover_floor)
    candidates = list(candidate_symbols) if candidate_symbols is not None else get_tech_universe_symbols()
    selected: list[str] = []
    lookback = max(min_history_bars, liquidity_lookback_bars)
    for symbol in candidates:
        bars = store.get_ohlcv_as_of(str(symbol), as_of_date, lookback)
        if bars is None or len(bars) < min_history_bars:
            continue
        if max_staleness_days is not None:
            last_bar_date = str(bars["date"].iloc[-1])[:10]
            if (pd.Timestamp(as_of_date) - pd.Timestamp(last_bar_date)).days > max_staleness_days:
                continue
        turnover = pd.to_numeric(bars["turnover"].tail(liquidity_lookback_bars), errors="coerce").dropna()
        if len(turnover) < liquidity_lookback_bars:
            continue
        if float(turnover.mean()) >= floor:
            selected.append(str(symbol))
    return sorted(selected)


def _turnover_floor(explicit: float | None) -> float:
    if explicit is not None:
        return float(explicit)
    params = load_params()
    canslim = params.get("backtest", {}).get("canslim", {})
    if "universe_turnover_floor" in canslim:
        return float(canslim["universe_turnover_floor"])
    return float(params["risk"]["rules"]["R-6"]["thresholds"]["avg_turnover_20_below_twd"])
