"""Backtest framework for the surge-candidates screener.

Modules:
- historical_data_store: SQLite OHLCV cache for point-in-time replay
- signal_replay:         day-by-day replay of evaluate_surge_candidate
- trade_simulator:       entry/exit simulation (3 exit rules)
- metrics:               win rate, Sharpe, max DD, profit factor, expectancy
- report_generator:      Markdown + CSV outputs
"""
