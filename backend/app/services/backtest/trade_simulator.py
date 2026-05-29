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
from backend.app.services.strategy.canslim.params import load_params as load_canslim_params

logger = logging.getLogger(__name__)

CANSLIM_CANDIDATE_TYPE = "CANSLIM觀察"


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
    entry_tier INTEGER DEFAULT 0,
    position_multiplier REAL DEFAULT 1.0,
    PRIMARY KEY (run_id, trade_id)
);
CREATE INDEX IF NOT EXISTS idx_trades_run ON backtest_trades(run_id);
"""


class ExitReason(str, Enum):
    HOLD_DAYS = "hold_days_expired"
    STOP_LOSS = "stop_loss_triggered"
    STOP_LOSS_LIMIT_DOWN_NEXT_OPEN = "stop_loss_triggered_limit_down_next_open"
    TARGET_REACHED = "target_reached"
    NO_EXIT_DATA = "no_exit_data"


class EntryStatus(str, Enum):
    FILLED = "filled"
    SKIPPED_NO_NEXT_DAY = "skipped_no_next_day_data"
    SKIPPED_LIMIT_UP = "skipped_open_limit_up"
    SKIPPED_TIER_LOW = "skipped_tier_below_min"
    SKIPPED_INVALID_PRICE = "skipped_invalid_price_data"


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
    round_trip_cost_pct: Optional[float] = None
    atr_stop_multiplier: float = 0.0
    trailing_ma_days: int = 0
    entry_on_signal_candidate_types: tuple[str, ...] = (CANSLIM_CANDIDATE_TYPE,)
    # Phase 11: tiered position sizing. entry_tier=0 means legacy signal and
    # remains accepted at 1.0x for backward compatibility.
    tier_position_multipliers: dict[int, float] = field(
        default_factory=lambda: {1: 0.5, 2: 1.0, 3: 1.5}
    )
    min_entry_tier: int = 1
    # Phase 12 v2: Taiwan daily price-limit model. Kept opt-in so v1 tests and
    # historical reports retain their original fill assumptions.
    include_tw_price_limit: bool = False


def canslim_trade_rules_from_params() -> TradeRules:
    # I1 deliberately uses single-entry trades. The YAML keeps
    # pyramiding_enabled for I2 calibration, where add-on entries can be tested
    # without changing this first signal/trade-flow fixture.
    params = load_canslim_params()
    backtest = params["backtest"]
    stops = backtest["stops"]
    costs = backtest["costs"]
    canslim = backtest["canslim"]
    return TradeRules(
        max_hold_days=int(canslim.get("max_hold_days", 30)),
        stop_loss_pct=float(stops["initial_stop_pct"]),
        target_pct=0.15,
        measured_move_method="box_range",
        measured_move_multiplier=1.0,
        commission_pct=0.0,
        transaction_tax_pct=0.0,
        slippage_pct=0.0,
        round_trip_cost_pct=float(costs["round_trip_cost_pct"]),
        atr_stop_multiplier=float(stops.get("atr_stop_multiplier", 0.0)),
        trailing_ma_days=60,
    )


@dataclass
class SimulationSummary:
    run_id: str
    trades_filled: int
    trades_skipped: int
    avg_hold_days: float
    win_rate: float
    avg_net_return_pct: float


_SCHEMA_INITIALIZED: set[str] = set()


def _migrate_trades_schema(conn: sqlite3.Connection) -> None:
    cursor = conn.execute("PRAGMA table_info(backtest_trades)")
    existing = {row[1] for row in cursor.fetchall()}
    for col, typ in (
        ("entry_tier", "INTEGER DEFAULT 0"),
        ("position_multiplier", "REAL DEFAULT 1.0"),
    ):
        if col not in existing:
            try:
                conn.execute(f"ALTER TABLE backtest_trades ADD COLUMN {col} {typ}")
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc).lower():
                    raise


def initialize_trade_schema(db_path: Path | str) -> None:
    # Phase 9.8: skip if already done in this process.
    key = str(Path(db_path).resolve())
    if key in _SCHEMA_INITIALIZED:
        return
    conn = sqlite3.connect(db_path)
    try:
        # Phase 9.8 speedup: WAL + relaxed sync for concurrent worker writes.
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript(_SCHEMA_SQL)
        _migrate_trades_schema(conn)
        conn.commit()
    finally:
        conn.close()
    _SCHEMA_INITIALIZED.add(key)


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
        sig_tier = _signal_entry_tier(sig)
        position_multiplier = _position_multiplier(sig_tier, rules)
        if sig_tier > 0 and sig_tier < rules.min_entry_tier:
            trades.append(_skip_record(run_id, next_trade_id, stock_id, signal_date, EntryStatus.SKIPPED_TIER_LOW, sig, rules))
            next_trade_id += 1
            skipped += 1
            continue

        # Phase 9.8: time-exit lookup window.
        # - max_hold_days > 0 → exact (2× + 10 day buffer for weekends/holidays)
        # - max_hold_days = 0 → 180 days cap (was 365 in earlier version; cut in
        #   half because typical Measured Move targets fire in 30-90 trading days,
        #   and 365-day walks were causing 10× slowdown in trade simulation).
        #   180 trading days ≈ 9 months, still well within Flat Base hold range.
        if rules.max_hold_days > 0:
            lookup_days = rules.max_hold_days * 2 + 10
        else:
            lookup_days = 180
        future_window = data_store.get_ohlcv(stock_id, signal_date, _add_days(signal_date, lookup_days))
        enter_on_signal_date = _entry_on_signal_date(sig, rules)
        if enter_on_signal_date:
            future_window = future_window[future_window["date"] >= signal_date].reset_index(drop=True)
        else:
            # Filter strictly AFTER signal_date
            future_window = future_window[future_window["date"] > signal_date].reset_index(drop=True)
        future_window = future_window[_valid_price_mask(future_window)].reset_index(drop=True)

        if len(future_window) < 1:
            trades.append(_skip_record(run_id, next_trade_id, stock_id, signal_date, EntryStatus.SKIPPED_NO_NEXT_DAY, sig, rules))
            next_trade_id += 1
            skipped += 1
            continue

        entry_row = future_window.iloc[0]
        # Detect open-limit-up: low == high AND change vs prev close > +9.5% → can't buy
        # (simplified — actual Taiwan rule is ±10% with tolerance)
        prev_close = float(sig["close_price"])
        if prev_close <= 0:
            trades.append(_skip_record(run_id, next_trade_id, stock_id, signal_date, EntryStatus.SKIPPED_INVALID_PRICE, sig, rules))
            next_trade_id += 1
            skipped += 1
            continue
        if prev_close > 0 and entry_row["open"] >= prev_close * 1.095 and entry_row["high"] == entry_row["low"]:
            trades.append(_skip_record(run_id, next_trade_id, stock_id, signal_date, EntryStatus.SKIPPED_LIMIT_UP, sig, rules))
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
        initial_stop_price = _initial_stop_price(entry_price, sig, rules)
        exit_date, exit_price, exit_reason, hold_days = _walk_until_exit(
            future_window.iloc[1:], entry_price, rules, dynamic_target=signal_target_price,
            previous_close=float(entry_row["close"]), initial_stop_price=initial_stop_price,
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
        trade_cost = (
            float(rules.round_trip_cost_pct)
            if rules.round_trip_cost_pct is not None
            else rules.commission_pct * 2 + rules.transaction_tax_pct
        )
        # Phase 11: net_return_pct is portfolio impact after tier sizing.
        # Costs scale with position size because commission/tax are trade-value based.
        effective_gross_return = gross_return * position_multiplier
        net_return = (gross_return - trade_cost) * position_multiplier

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
            "gross_return_pct": round(effective_gross_return, 6),
            "net_return_pct": round(net_return, 6),
            "entry_status": EntryStatus.FILLED.value,
            "candidate_type": sig.get("candidate_type"),
            "sector_category": sig.get("sector_category"),
            "entry_tier": sig_tier,
            "position_multiplier": position_multiplier,
        })
        next_trade_id += 1

    _persist_trades(db_path, trades)

    filled = [t for t in trades if t["entry_status"] == EntryStatus.FILLED.value]
    if not filled:
        empty = SimulationSummary(run_id=run_id, trades_filled=0, trades_skipped=skipped,
                                   avg_hold_days=0.0, win_rate=0.0, avg_net_return_pct=0.0)
        empty.trade_rows = trades  # type: ignore[attr-defined]
        return empty
    win_count = sum(1 for t in filled if t["net_return_pct"] > 0)
    summary = SimulationSummary(
        run_id=run_id,
        trades_filled=len(filled),
        trades_skipped=skipped,
        avg_hold_days=sum(t["hold_days"] for t in filled) / len(filled),
        win_rate=win_count / len(filled),
        avg_net_return_pct=sum(t["net_return_pct"] for t in filled) / len(filled),
    )
    # Phase 9.8 speedup: also expose trade rows so caller can skip load_trades DB read.
    summary.trade_rows = trades  # type: ignore[attr-defined]
    return summary


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


def _signal_entry_tier(sig) -> int:
    raw = sig.get("entry_tier", 0) if hasattr(sig, "get") else 0
    if pd.isna(raw):
        return 0
    try:
        return max(0, min(4, int(raw)))
    except (TypeError, ValueError):
        return 0


def _valid_price_mask(bars: pd.DataFrame) -> pd.Series:
    if bars.empty:
        return pd.Series(dtype=bool)
    prices = bars[["open", "high", "low", "close"]].apply(pd.to_numeric, errors="coerce")
    return prices.gt(0).all(axis=1)


def _position_multiplier(entry_tier: int, rules: TradeRules) -> float:
    if entry_tier <= 0:
        return 1.0
    return float(rules.tier_position_multipliers.get(entry_tier, 1.0))


def _entry_on_signal_date(sig, rules: TradeRules) -> bool:
    candidate_type = sig.get("candidate_type") if hasattr(sig, "get") else None
    return str(candidate_type) in set(rules.entry_on_signal_candidate_types)


def _initial_stop_price(entry_price: float, sig, rules: TradeRules) -> float:
    pct_stop = entry_price * (1 - rules.stop_loss_pct)
    atr = sig.get("atr20") if hasattr(sig, "get") else None
    if rules.atr_stop_multiplier > 0 and atr is not None and not pd.isna(atr) and float(atr) > 0:
        atr_stop = entry_price - float(atr) * rules.atr_stop_multiplier
        return max(pct_stop, atr_stop)
    return pct_stop


def _walk_until_exit(
    future_bars: pd.DataFrame,
    entry_price: float,
    rules: TradeRules,
    *,
    dynamic_target: Optional[float] = None,
    previous_close: Optional[float] = None,
    initial_stop_price: Optional[float] = None,
) -> tuple[Optional[str], Optional[float], Optional[str], int]:
    """Walk forward day-by-day; return (exit_date, exit_price, exit_reason, hold_days).

    Phase 9.8:
      - dynamic_target overrides target_pct when provided
      - max_hold_days=0 disables the time-out exit (hold to target/stop only)
    """
    stop_price = initial_stop_price if initial_stop_price is not None else entry_price * (1 - rules.stop_loss_pct)
    target_price = dynamic_target if dynamic_target is not None else entry_price * (1 + rules.target_pct)

    bars = future_bars.reset_index(drop=True)
    prev_close = float(previous_close) if previous_close and previous_close > 0 else entry_price

    for pos, bar in bars.iterrows():
        hold_days = int(pos) + 1
        low = float(bar["low"])
        high = float(bar["high"])
        close = float(bar["close"])
        date = str(bar["date"])

        # Check stop-loss first (worst-case assumption: stop trips when low touches)
        if low <= stop_price:
            if rules.include_tw_price_limit and _is_tw_limit_down_bar(bar, prev_close):
                return _exit_after_limit_down(bars, int(pos), stop_price)
            return date, stop_price, ExitReason.STOP_LOSS.value, hold_days
        # Check target
        if high >= target_price:
            return date, target_price, ExitReason.TARGET_REACHED.value, hold_days
        # Check max hold (skipped when max_hold_days <= 0 = unlimited)
        if rules.max_hold_days > 0 and hold_days >= rules.max_hold_days:
            return date, close, ExitReason.HOLD_DAYS.value, hold_days
        prev_close = close

    return None, None, None, 0


def _is_tw_limit_down_bar(bar, previous_close: float, *, tolerance: float = 0.005) -> bool:
    """Simplified Taiwan locked limit-down detection.

    A locked limit-down bar has no real liquidity (`high == low`) near the
    -10% daily limit, so a stop cannot be assumed filled at the stop price.
    """
    if previous_close <= 0:
        return False
    low = float(bar["low"])
    high = float(bar["high"])
    open_price = float(bar["open"])
    limit_down_price = previous_close * 0.90
    locked = abs(high - low) <= max(previous_close * 0.0001, 0.01)
    near_limit = open_price <= previous_close * (0.90 + tolerance) or low <= limit_down_price * (1 + tolerance)
    return locked and near_limit


def _exit_after_limit_down(
    bars: pd.DataFrame,
    limit_pos: int,
    stop_price: float,
) -> tuple[Optional[str], Optional[float], Optional[str], int]:
    """Exit at the next tradable open after a locked limit-down stop trigger."""
    prev_close = float(bars.iloc[limit_pos]["close"])
    for next_pos in range(limit_pos + 1, len(bars)):
        next_bar = bars.iloc[next_pos]
        if not _is_tw_limit_down_bar(next_bar, prev_close):
            return (
                str(next_bar["date"]),
                float(next_bar["open"]),
                ExitReason.STOP_LOSS_LIMIT_DOWN_NEXT_OPEN.value,
                next_pos + 1,
            )
        prev_close = float(next_bar["close"])

    # No tradable next day in the lookup window. Use the final close as the
    # least optimistic liquidation proxy and mark the special reason.
    last = bars.iloc[-1]
    return (
        str(last["date"]),
        min(float(last["close"]), stop_price),
        ExitReason.STOP_LOSS_LIMIT_DOWN_NEXT_OPEN.value,
        len(bars),
    )


def _skip_record(run_id: str, trade_id: int, stock_id: str, signal_date: str,
                  status: EntryStatus, sig, rules: Optional[TradeRules] = None) -> dict:
    entry_tier = _signal_entry_tier(sig)
    effective_rules = rules or TradeRules()
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
        "entry_tier": entry_tier,
        "position_multiplier": _position_multiplier(entry_tier, effective_rules),
    }


def _persist_trades(db_path: Path | str, rows: Iterable[dict]) -> int:
    rows = list(rows)
    if not rows:
        return 0
    sql = """
        INSERT OR REPLACE INTO backtest_trades
          (run_id, trade_id, stock_id, signal_date, entry_date, entry_price,
           exit_date, exit_price, exit_reason, hold_days, gross_return_pct,
           net_return_pct, entry_status, candidate_type, sector_category,
           entry_tier, position_multiplier)
        VALUES (:run_id, :trade_id, :stock_id, :signal_date, :entry_date, :entry_price,
                :exit_date, :exit_price, :exit_reason, :hold_days, :gross_return_pct,
                :net_return_pct, :entry_status, :candidate_type, :sector_category,
                :entry_tier, :position_multiplier)
    """
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA synchronous=NORMAL")
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
