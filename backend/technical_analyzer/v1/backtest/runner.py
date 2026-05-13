"""CLI entry point for Taiwan stock v2-preview backtests."""

from __future__ import annotations

import argparse
from datetime import date
from decimal import Decimal
from pathlib import Path

from .engine import run_backtest
from .models import BacktestConfig


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Taiwan stock AI v2-preview backtests.")
    parser.add_argument("--symbols", required=True, help="Comma-separated symbols, e.g. 2330,2454,2317")
    parser.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="End date YYYY-MM-DD")
    parser.add_argument("--data-dir", default=None, help="Optional directory containing <symbol>.csv OHLCV files")
    parser.add_argument("--output-dir", default="backend/backtest_results", help="Output directory")
    parser.add_argument("--initial-capital", default="1000000")
    parser.add_argument("--base-position-pct", default="0.10")
    parser.add_argument("--max-position-pct", default="0.25")
    parser.add_argument("--min-signal", type=int, default=60)
    parser.add_argument("--min-confidence", type=int, default=45)
    parser.add_argument("--max-risk", type=int, default=75)
    parser.add_argument("--max-holding-days", type=int, default=20)
    parser.add_argument("--forward-days", type=int, default=20)
    parser.add_argument("--warmup-bars", type=int, default=140)
    parser.add_argument("--fee-rate", default="0.001425")
    parser.add_argument("--tax-rate", default="0.003")
    parser.add_argument("--slippage-bps", default="5")
    parser.add_argument("--require-rr-pass", action="store_true", help="Strict v2 mode: require RR >= 3")
    parser.add_argument("--block-fundamental-unknown", action="store_true", help="Reject trades when fundamental data is missing")
    parser.add_argument("--allow-mock", action="store_true", help="Allow generated mock candles if no CSV/FinMind data is available")
    args = parser.parse_args()

    config = BacktestConfig(
        symbols=[symbol.strip() for symbol in args.symbols.split(",") if symbol.strip()],
        start=date.fromisoformat(args.start),
        end=date.fromisoformat(args.end),
        initial_capital=Decimal(args.initial_capital),
        base_position_pct=Decimal(args.base_position_pct),
        max_position_pct=Decimal(args.max_position_pct),
        min_signal=args.min_signal,
        min_confidence=args.min_confidence,
        max_risk=args.max_risk,
        require_rr_pass=args.require_rr_pass,
        allow_fundamental_unknown=not args.block_fundamental_unknown,
        max_holding_days=args.max_holding_days,
        forward_days=args.forward_days,
        warmup_bars=args.warmup_bars,
        fee_rate=Decimal(args.fee_rate),
        tax_rate=Decimal(args.tax_rate),
        slippage_bps=Decimal(args.slippage_bps),
        data_dir=Path(args.data_dir) if args.data_dir else None,
        output_dir=Path(args.output_dir),
        allow_mock=args.allow_mock,
    )
    result = run_backtest(config)
    summary = result.summary
    print("Backtest complete")
    print(f"Symbols: {', '.join(config.symbols)}")
    print(f"Period: {config.start} ~ {config.end}")
    print(f"Trades: {summary.total_trades}")
    print(f"Total return: {summary.total_return_pct}%")
    print(f"Max drawdown: {summary.max_drawdown_pct}%")
    print(f"Win rate: {summary.win_rate if summary.win_rate is not None else 'N/A'}%")
    print(f"Excel: {result.generated_files.get('xlsx')}")
    print(f"Folder: {result.generated_files.get('run_dir')}")


if __name__ == "__main__":
    main()
