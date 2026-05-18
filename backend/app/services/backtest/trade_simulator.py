"""Trade simulation engine for the backtest framework.

For each signal:
1. Enter at NEXT trading day's OPEN price (no same-day fill bias)
2. Exit per the configured ExitRule:
   - FixedHoldDays: exit at close after N days
   - StopLoss: exit when low <= entry × (1 - stop_pct)
   - TargetReached: exit when high >= entry × (1 + target_pct)
   - Combined: monitor all exit conditions, whichever fires first

Output rows go to `backtest_trades` table.

Cost model (Taiwan stock):
  - Buy commission: trade_amount × 0.001425
  - Sell commission: trade_amount × 0.001425
  - Sell transaction tax: trade_amount × 0.003
  - Slippage: ±0.1% on each side (configurable)
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd

from backend.app.services.backtest.historical_data_store import HistoricalDataStore

logger = logging.getLogger(__name__)


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS backtest_trades (
    run_id TEXT NOT NULL,
    trade_id INTEGER NOT NULL,
    stock_id TEXT NOT NULL,
    signal_date TEXT NOT NULL,
    entry_date TEXT,
    entry_price REAL,
    exit_date TEXT,
    exit_price REAL,
    exit_reason TEXT,
    hold_days INTEGER,
    gross_return_pct REAL,
    net_return_pct REAL,
    entry_status TEXT,
    candidate_type TEXT,
    sector_category TEXT,
    PRIMARY KEY (run_id, trade_id)
);
CREATE INDEX IF NOT EXISTS idx_trades_run ON backtest_trades(run_id);
"""


class ExitReason(str, Enum):
    HOLD_DAYS = "hold_days_expired"
    STOP_LOSS = "stop_loss_triggered"
    TARGET_REACHED = "target_reached"
    NO_EXIT_DATA = "no_exit_data"


class EntryStatus(str, Enum):
    FILLED = "filled"
    SKIPPED_NO_NEXT_DAY = "skipped_no_next_day_data"
    SKIPPED_LIMIT_UP = "skipped_open_limit_up"


@dataclass
class TradeRules:
    """Exit rule configuration. All thresholds inclusive.

    Phase 9.8 (Flat Base O'Neil alignment):
    - max_hold_days = 0 → UNLIMITED time-in-position (hold until target or stop)
    - stop_loss_pct = 0.10 matches user thesis (-10% structure-failure rule)
    - measured_move_method:
        "fixed"     → use target_pct (legacy, +15%)
        "box_range" → entry + (base_high - base_low) × measured_move_multiplier
                      (O'Neil-style 0.85 multiplier, user-style 1.0; both supported)
    """
    max_hold_days: int = 0          # 0 = no time exit
    stop_loss_pct: float = 0.10     # -10% from entry → stop out (user thesis)
    target_pct: float = 0.15        # fallback when measured_move_method=="fixed"
    measured_move_method: str = "box_range"   # "box_range" | "fixed"
    measured_move_multiplier: float = 0.85    # O'Neil flat base standard
    # Costs (Taiwan stock defaults)
    commission_pct: float = 0.001425
    transaction_tax_pct: float = 0.003  # applied only on sell
    slippage_pct: float = 0.001         # on each side


@dataclass
class SimulationSummary:
    run_id: str
    trades_filled: int
    trades_skipped: int
    avg_hold_days: float
    win_rate: float
    avg_net_return_pct: float


def initialize_trade_schema(db_path: Path | str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(_SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()


def simulate_trades(
    *,
    signals_df: pd.DataFrame,
    data_store: HistoricalDataStore,
    rules: TradeRules,
    run_id: str,
    db_path: Path | str,
) -> SimulationSummary:
    """Simulate trades for every row in signals_df. Persists to backtest_trades."""
    initialize_trade_schema(db_path)

    trades: list[dict] = []
    skipped = 0
    next_trade_id = 1

    for _, sig in signals_df.iterrows():
        stock_id = str(sig["stock_id"])
        signal_date = str(sig["signal_date"])
        # Phase 9.8: when max_hold_days=0 (unlimited), look up to 365 calendar days
        # ahead so target/stop have time to fire. Otherwise legacy behavior.
        if rules.max_hold_days > 0:
            lookup_days = rules.max_hold_days * 2 + 10
        else:
            lookup_days = 365
        future_window = data_store.get_ohlcv(stock_id, signal_date, _add_days(signal_date, lookup_days))
        # Filter strictly AFTER signal_date
        future_window = future_window[future_window["date"] > signal_date].reset_index(drop=True)

        if len(future_window) < 1:
            trades.append(_skip_record(run_id, next_trade_id, stock_id, signal_date, EntryStatus.SKIPPED_NO_NEXT_DAY, sig))
            next_trade_id += 1
            skipped += 1
            continue

        entry_row = future_window.iloc[0]
        # Detect open-limit-up: low == high AND change vs prev close > +9.5% → can't buy
        # (simplified — actual Taiwan rule is ±10% with tolerance)
        prev_close = float(sig["close_price"])
        if prev_close > 0 and entry_row["open"] >= prev_close * 1.095 and entry_row["high"] == entry_row["low"]:
            trades.append(_skip_record(run_id, next_trade_id, stock_id, signal_date, EntryStatus.SKIPPED_LIMIT_UP, sig))
            next_trade_id += 1
            skipped += 1
            continue

        # Apply entry slippage (buy at slightly worse price)
        entry_price = float(entry_row["open"]) * (1 + rules.slippage_pct)
        entry_date = str(entry_row["date"])

        # Phase 9.8: dynamic Measured Move target.
        # entry + (base_high - base_low) × multiplier
        # If signal lacks base_high/base_low, fall back to fixed target_pct.
        signal_target_price = _compute_dynamic_target(entry_price, sig, rules)

        # Walk forward until exit
        exit_date, exit_price, exit_reason, hold_days = _walk_until_exit(
            future_window.iloc[1:], entry_price, rules, dynamic_target=signal_target_price,
        )

        if exit_date is None:
            # No data → close at last available
            last = future_window.iloc[-1]
            exit_date = str(last["date"])
            exit_price = float(last["close"])
            exit_reason = ExitReason.NO_EXIT_DATA.value
            hold_days = len(future_window) - 1

        # Apply exit slippage (sell at slightly worse price)
        exit_price_after_slip = exit_price * (1 - rules.slippage_pct)

        gross_return = (exit_price_after_slip - entry_price) / entry_price
        # Net = gross - buy commission - sell commission - tax
        net_return = gross_return - rules.commission_pct * 2 - rules.transaction_tax_pct

        trades.append({
            "run_id": run_id,
            "trade_id": next_trade_id,
            "stock_id": stock_id,
            "signal_date": signal_date,
            "entry_date": entry_date,
            "entry_price": round(entry_price, 4),
            "exit_date": exit_date,
            "exit_price": round(exit_price_after_slip, 4),
            "exit_reason": exit_reason,
            "hold_days": hold_days,
            "gross_return_pct": round(gross_return, 6),
            "net_return_pct": round(net_return, 6),
            "entry_status": EntryStatus.FILLED.value,
            "candidate_type": sig.get("candidate_type"),
            "sector_category": sig.get("sector_category"),
        })
        next_trade_id += 1

    _persist_trades(db_path, trades)

    filled = [t for t in trades if t["entry_status"] == EntryStatus.FILLED.value]
    if not filled:
        return SimulationSummary(run_id=run_id, trades_filled=0, trades_skipped=skipped,
                                  avg_hold_days=0.0, win_rate=0.0, avg_net_return_pct=0.0)
    win_count = sum(1 for t in filled if t["net_return_pct"] > 0)
    return SimulationSummary(
        run_id=run_id,
        trades_filled=len(filled),
        trades_skipped=skipped,
        avg_hold_days=sum(t["hold_days"] for t in filled) / len(filled),
        win_rate=win_count / len(filled),
        avg_net_return_pct=sum(t["net_return_pct"] for t in filled) / len(filled),
    )


def _compute_dynamic_target(entry_price: float, sig, rules: TradeRules) -> float:
    """Return target price for this trade based on rules.measured_move_method.

    Falls back to fixed target_pct when:
      - method == "fixed"
      - method == "box_range" but signal lacks base_high/base_low (legacy signals)
    """
    if rules.measured_move_method == "box_range":
        base_high = sig.get("base_high") if hasattr(sig, "get") else None
        base_low = sig.get("base_low") if hasattr(sig, "get") else None
        if base_high and base_low and base_high > base_low > 0:
            box_range = float(base_high) - float(base_low)
            return entry_price + box_range * rules.measured_move_multiplier
    # Fallback: fixed percentage
    return entry_price * (1 + rules.target_pct)


def _walk_until_exit(
    future_bars: pd.DataFrame,
    entry_price: float,
    rules: TradeRules,
    *,
    dynamic_target: Optional[float] = None,
) -> tuple[Optional[str], Optional[float], Optional[str], int]:
    """Walk forward day-by-day; return (exit_date, exit_price, exit_reason, hold_days).

    Phase 9.8:
      - dynamic_target overrides target_pct when provided
      - max_hold_days=0 disables the time-out exit (hold to target/stop only)
    """
    stop_price = entry_price * (1 - rules.stop_loss_pct)
    target_price = dynamic_target if dynamic_target is not None else entry_price * (1 + rules.target_pct)

    for hold_days, (_, bar) in enumerate(future_bars.iterrows(), start=1):
        low = float(bar["low"])
        high = float(bar["high"])
        close = float(bar["close"])
        date = str(bar["date"])

        # Check stop-loss first (worst-case assumption: stop trips when low touches)
        if low <= stop_price:
            return date, stop_price, ExitReason.STOP_LOSS.value, hold_days
        # Check target
        if high >= target_price:
            return date, target_price, ExitReason.TARGET_REACHED.value, hold_days
        # Check max hold (skipped when max_hold_days <= 0 = unlimited)
        if rules.max_hold_days > 0 and hold_days >= rules.max_hold_days:
            return date, close, ExitReason.HOLD_DAYS.value, hold_days

    return None, None, None, 0


def _skip_record(run_id: str, trade_id: int, stock_id: str, signal_date: str,
                  status: EntryStatus, sig) -> dict:
    return {
        "run_id": run_id,
        "trade_id": trade_id,
        "stock_id": stock_id,
        "signal_date": signal_date,
        "entry_date": None,
        "entry_price": None,
        "exit_date": None,
        "exit_price": None,
        "exit_reason": None,
        "hold_days": 0,
        "gross_return_pct": None,
        "net_return_pct": None,
        "entry_status": status.value,
        "candidate_type": sig.get("candidate_type") if hasattr(sig, "get") else None,
        "sector_category": sig.get("sector_category") if hasattr(sig, "get") else None,
    }


def _persist_trades(db_path: Path | str, rows: Iterable[dict]) -> int:
    rows = list(rows)
    if not rows:
        return 0
    sql = """
        INSERT OR REPLACE INTO backtest_trades
          (run_id, trade_id, stock_id, signal_date, entry_date, entry_price,
           exit_date, exit_price, exit_reason, hold_days, gross_return_pct,
           net_return_pct, entry_status, candidate_type, sector_category)
        VALUES (:run_id, :trade_id, :stock_id, :signal_date, :entry_date, :entry_price,
                :exit_date, :exit_price, :exit_reason, :hold_days, :gross_return_pct,
                :net_return_pct, :entry_status, :candidate_type, :sector_category)
    """
    conn = sqlite3.connect(db_path)
    try:
        conn.executemany(sql, rows)
        conn.commit()
    finally:
        conn.close()
    return len(rows)


def load_trades(db_path: Path | str, run_id: str) -> pd.DataFrame:
    conn = sqlite3.connect(db_path)
    try:
        df = pd.read_sql_query(
            "SELECT * FROM backtest_trades WHERE run_id = ? ORDER BY trade_id ASC",
            conn,
            params=(run_id,),
        )
    finally:
        conn.close()
    return df


def _add_days(date_str: str, days: int) -> str:
    """Calendar-day add — coarse but fine for upper bound lookup."""
    from datetime import datetime, timedelta
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return (dt + timedelta(days=days)).strftime("%Y-%m-%d")
