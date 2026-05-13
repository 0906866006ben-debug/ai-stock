"""Backtesting package for technical analyzer v1/v2-preview."""

from .engine import run_backtest
from .models import BacktestConfig, BacktestResult, BacktestSummary, DailySignal, HypothesisBacktestRow, Trade

__all__ = [
    "BacktestConfig",
    "BacktestResult",
    "BacktestSummary",
    "DailySignal",
    "HypothesisBacktestRow",
    "Trade",
    "run_backtest",
]
