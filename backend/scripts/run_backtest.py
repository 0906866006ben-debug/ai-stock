"""End-to-end backtest CLI.

Usage:
    python -m backend.scripts.run_backtest \
        --start 2024-01-01 --end 2024-12-31 \
        --universe-file backend/data/sectors/ai_tech_tw.json \
        --hold-days 20 --stop-loss 0.07 --target 0.15 \
        --output report.md

Workflow:
    1. Build stock universe (from AI tech whitelist by default)
    2. Replay signals day-by-day → backtest_signals table
    3. Simulate trades → backtest_trades table
    4. Compute metrics and write Markdown report
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from backend.app.services.backtest.historical_data_store import HistoricalDataStore, DEFAULT_DB_PATH
from backend.app.services.backtest.report_generator import (
    export_trades_csv,
    generate_markdown_report,
    save_report,
)
from backend.app.services.backtest.signal_replay import (
    ReplayConfig,
    generate_run_id,
    load_signals,
    replay_signals,
)
from backend.app.services.backtest.trade_simulator import (
    TradeRules,
    load_trades,
    simulate_trades,
)


logger = logging.getLogger(__name__)


def load_ai_tech_universe(json_path: Path) -> list[str]:
    """Extract all stock codes from the 6-Layer Framework whitelist."""
    with json_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    codes: list[str] = []
    for cat in data.get("categories", {}).values():
        for stock in cat.get("stocks", []):
            code = str(stock.get("code", "")).strip()
            if code:
                codes.append(code)
    return codes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run backtest on the surge-candidates screener")
    parser.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="End date YYYY-MM-DD")
    parser.add_argument(
        "--universe-file",
        default=str(Path(__file__).resolve().parent.parent / "data" / "sectors" / "ai_tech_tw.json"),
        help="JSON file with whitelist; default = AI Tech 6-Layer Framework",
    )
    parser.add_argument("--stocks", nargs="*", help="Override universe with explicit stock list")
    parser.add_argument("--candidate-types", nargs="+", default=["起漲前觀察"],
                        help="Target candidate types to track (default 起漲前觀察)")
    parser.add_argument("--hold-days", type=int, default=20)
    parser.add_argument("--stop-loss", type=float, default=0.07, help="Stop loss as decimal (0.07 = 7%)")
    parser.add_argument("--target", type=float, default=0.15, help="Profit target as decimal")
    parser.add_argument("--commission", type=float, default=0.001425)
    parser.add_argument("--tax", type=float, default=0.003)
    parser.add_argument("--slippage", type=float, default=0.001)
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite DB path")
    parser.add_argument("--output", default="backtest_report.md", help="Markdown report output path")
    parser.add_argument("--csv-output", default=None, help="Optional CSV trades export")
    parser.add_argument("--run-id", default=None, help="Custom run_id; default auto-generated")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    # Build universe
    if args.stocks:
        universe = args.stocks
    else:
        universe_path = Path(args.universe_file)
        if not universe_path.exists():
            logger.error("Universe file not found: %s", universe_path)
            return 2
        universe = load_ai_tech_universe(universe_path)

    if not universe:
        logger.error("Empty universe")
        return 2

    logger.info("Backtest universe size: %d stocks", len(universe))

    # Data store
    store = HistoricalDataStore(args.db)
    if store.row_count() == 0:
        logger.error("No OHLCV data in %s. Run download_history.py first.", args.db)
        return 3

    # Run config
    run_id = args.run_id or generate_run_id()
    replay_config = ReplayConfig(
        run_id=run_id,
        start_date=args.start,
        end_date=args.end,
        stock_universe=universe,
        target_candidate_types=args.candidate_types,
    )
    logger.info("Replay config: %s", replay_config)

    def progress(payload: dict) -> None:
        if args.verbose:
            logger.info("Day %s/%s, signals=%s",
                        payload["day_idx"], payload["total_days"], payload["signals_so_far"])

    # ── Step 1: replay signals ───────────────────────────────────────────────
    logger.info("Step 1: replaying signals...")
    replay_summary = replay_signals(replay_config, data_store=store, db_path=args.db, progress_callback=progress)
    logger.info("Replay done: %s signals over %s days", replay_summary.signals_generated, replay_summary.days_processed)

    # ── Step 2: simulate trades ──────────────────────────────────────────────
    signals_df = load_signals(args.db, run_id)
    if signals_df.empty:
        logger.warning("No signals generated — backtest is empty")
        sys.exit(0)

    rules = TradeRules(
        max_hold_days=args.hold_days,
        stop_loss_pct=args.stop_loss,
        target_pct=args.target,
        commission_pct=args.commission,
        transaction_tax_pct=args.tax,
        slippage_pct=args.slippage,
    )
    logger.info("Step 2: simulating trades with rules %s", rules)
    sim_summary = simulate_trades(signals_df=signals_df, data_store=store, rules=rules, run_id=run_id, db_path=args.db)
    logger.info("Simulation done: %s filled, %s skipped, win_rate=%.2f%%, avg_return=%.2f%%",
                sim_summary.trades_filled, sim_summary.trades_skipped,
                sim_summary.win_rate*100, sim_summary.avg_net_return_pct*100)

    # ── Step 3: generate report ─────────────────────────────────────────────
    trades_df = load_trades(args.db, run_id)
    config_summary = {
        "run_id": run_id,
        "date_range": f"{args.start} → {args.end}",
        "universe_size": len(universe),
        "candidate_types": ", ".join(args.candidate_types),
        "hold_days": args.hold_days,
        "stop_loss_pct": f"{args.stop_loss*100:.1f}%",
        "target_pct": f"{args.target*100:.1f}%",
        "commission": f"{args.commission*100:.4f}%",
        "tax": f"{args.tax*100:.2f}%",
        "slippage": f"{args.slippage*100:.2f}%",
    }
    report = generate_markdown_report(
        run_id=run_id,
        config_summary=config_summary,
        trades_df=trades_df,
        signals_df=signals_df,
    )
    save_report(report, args.output)
    logger.info("Report saved to %s", args.output)

    if args.csv_output:
        export_trades_csv(trades_df, args.csv_output)
        logger.info("CSV exported to %s", args.csv_output)

    return 0


if __name__ == "__main__":
    sys.exit(main())
