"""Day-by-day signal replay for backtest.

Critical invariant — NO LOOKAHEAD BIAS:
  When evaluating "2023-06-15", we ONLY use OHLCV bars with date <= 2023-06-15.

For each trading day in [start_date, end_date]:
  1. For each stock in universe, load most recent N bars (e.g. 150) up to that day
  2. Run evaluate_surge_candidate on that point-in-time slice
  3. Collect all signals whose candidate_type matches target (e.g. "起漲前觀察")
  4. Persist into backtest_signals table

The result is a complete historical record of "what would the screener have
flagged on each day in the past?"
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd

from backend.app.services.backtest.historical_data_store import HistoricalDataStore
from backend.app.services.screener_rules import load_surge_candidate_rules
from backend.app.services.screener_service import (
    _canonicalize_ohlcv,
    _compute_base_features,
    evaluate_surge_candidate,
)

logger = logging.getLogger(__name__)


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS backtest_signals (
    run_id TEXT NOT NULL,
    signal_date TEXT NOT NULL,
    stock_id TEXT NOT NULL,
    candidate_type TEXT,
    surge_candidate_score INTEGER,
    pre_breakout_score INTEGER,
    confidence_score INTEGER,
    risk_score INTEGER,
    close_price REAL,
    range_90d REAL,
    return_60d REAL,
    return_20d REAL,
    volume_contraction_ratio REAL,
    ema_spread REAL,
    sector_category TEXT,
    base_high REAL,
    base_low REAL,
    avg_volume_50 REAL,
    PRIMARY KEY (run_id, signal_date, stock_id)
);
CREATE INDEX IF NOT EXISTS idx_signals_date ON backtest_signals(signal_date);
CREATE INDEX IF NOT EXISTS idx_signals_type ON backtest_signals(candidate_type);
-- Backwards-compat: existing DBs need new columns added separately (idempotent).
"""


def _migrate_signals_schema(conn: sqlite3.Connection) -> None:
    """Add new columns to backtest_signals if missing.

    Safe to run from multiple worker processes concurrently: SQLite serializes
    the ALTER TABLE via file lock, and we catch the "duplicate column" error
    that fires when another worker won the race.
    """
    cursor = conn.execute("PRAGMA table_info(backtest_signals)")
    existing = {row[1] for row in cursor.fetchall()}
    for col, typ in (("base_high", "REAL"), ("base_low", "REAL"), ("avg_volume_50", "REAL")):
        if col not in existing:
            try:
                conn.execute(f"ALTER TABLE backtest_signals ADD COLUMN {col} {typ}")
            except sqlite3.OperationalError as exc:
                # Concurrent worker added the column between our check and ALTER.
                if "duplicate column name" not in str(exc).lower():
                    raise


@dataclass
class ReplayConfig:
    run_id: str
    start_date: str            # YYYY-MM-DD inclusive
    end_date: str              # YYYY-MM-DD inclusive
    stock_universe: list[str]  # list of stock_ids to test
    target_candidate_types: list[str] = field(default_factory=lambda: ["起漲前觀察"])
    lookback_bars: int = 150   # how many bars of history each evaluation needs
    market_df: Optional[pd.DataFrame] = None  # TAIEX history for RS computation


@dataclass
class ReplaySummary:
    run_id: str
    days_processed: int
    signals_generated: int
    by_type: dict[str, int]


# ───────────────────────────────────────────────────────────────────────────
# Process-level feature cache.
#
# Reused across all trials in one optimizer session. Key: (stock_id, as_of_date).
# Value: dict returned by _compute_base_features (a "feature snapshot").
#
# Why this is safe: the rules consumed inside _compute_base_features
# (return_90d_lookback_bars, lots_per_share, initial_move_spread,
# ema*_micro_upturn / flat thresholds, overheat_return_5d, upper_shadow_*,
# climax_volume_ratio, weak_close_position, extended_from_ema20) are NOT in
# the optimizer's search space, so the features are stable across trials.
#
# The cache key includes a `cache_namespace` token (default: rules path)
# so different sessions don't poison each other. Caller can reset via
# `reset_feature_cache()`.
# ───────────────────────────────────────────────────────────────────────────

_FEATURE_CACHE: dict[tuple[str, str, str], Optional[dict]] = {}


# Rule keys whose values affect _compute_base_features output.
# Hash these to form a cache namespace — if any change, cache is invalidated.
_SHAPE_KEYS = (
    "price_position.return_90d_lookback_bars",
    "volume.lots_per_share",
    "ema.initial_move_spread",
    "ema.ema5_micro_upturn_min",
    "ema.ema10_flat_floor",
    "ema.ema20_flat_floor",
    "price_position.overheat_return_5d",
    "candle.upper_shadow_ratio",
    "volume.upper_shadow_volume_ratio",
    "volume.climax_volume_ratio",
    "candle.weak_close_position",
    "ema.extended_from_ema20",
    "history.minimum_days",
)


def _cache_namespace(rules: dict) -> str:
    """Hash of shape-affecting rule values. If any of these changes, namespace
    changes → cache miss → safe recompute."""
    import hashlib
    parts = []
    for key in _SHAPE_KEYS:
        cursor: Any = rules
        for segment in key.split("."):
            cursor = cursor.get(segment) if isinstance(cursor, dict) else None
            if cursor is None:
                break
        parts.append(f"{key}={cursor}")
    blob = "|".join(parts)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


def reset_feature_cache() -> None:
    """Clear the feature cache. Call between optimizer sessions or when rules
    shape parameters (lookback windows etc.) might have changed."""
    _FEATURE_CACHE.clear()


def feature_cache_size() -> int:
    return len(_FEATURE_CACHE)


def initialize_replay_schema(db_path: Path | str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(_SCHEMA_SQL)
        _migrate_signals_schema(conn)
        conn.commit()
    finally:
        conn.close()


def replay_signals(
    config: ReplayConfig,
    *,
    data_store: HistoricalDataStore,
    db_path: Path | str,
    progress_callback=None,
) -> ReplaySummary:
    """Run the day-by-day signal replay.

    Writes results into `backtest_signals` table on `db_path`.
    Returns aggregate summary.
    """
    initialize_replay_schema(db_path)

    trading_dates = data_store.get_all_trading_dates(config.start_date, config.end_date)
    if not trading_dates:
        logger.warning("No trading dates found in [%s, %s]", config.start_date, config.end_date)
        return ReplaySummary(run_id=config.run_id, days_processed=0, signals_generated=0, by_type={})

    rows_to_persist: list[dict] = []
    by_type_counter: dict[str, int] = {t: 0 for t in config.target_candidate_types}
    days_processed = 0

    # Resolve cache namespace ONCE for this session — the shape rules don't
    # change between trials, so this hash is constant for the whole replay.
    cur_rules = load_surge_candidate_rules()
    namespace = _cache_namespace(cur_rules)

    cache_hits = 0
    cache_misses = 0

    for day_idx, as_of_date in enumerate(trading_dates):
        # Point-in-time market frame (TAIEX up to this date)
        market_slice = None
        if config.market_df is not None and not config.market_df.empty:
            market_slice = _slice_market_to_date(config.market_df, as_of_date, config.lookback_bars)

        for stock_id in config.stock_universe:
            df_hist = data_store.get_ohlcv_as_of(stock_id, as_of_date, config.lookback_bars)
            if len(df_hist) < 65:   # need history.minimum_days
                continue

            # Rename columns to PascalCase (evaluate_surge_candidate's _canonicalize_ohlcv expects this)
            df_eval = df_hist.rename(
                columns={"open": "Open", "high": "High", "low": "Low",
                         "close": "Close", "volume": "Volume", "turnover": "Turnover"}
            )

            # ── Feature cache lookup ────────────────────────────────────
            cache_key = (namespace, stock_id, as_of_date)
            cached_features = _FEATURE_CACHE.get(cache_key)
            if cached_features is None and cache_key not in _FEATURE_CACHE:
                # Cache miss — compute features once and store. We replicate the
                # validation steps from evaluate_surge_candidate's setup so the
                # cached features come from an identical canonicalized DataFrame.
                try:
                    normalized, has_turnover = _canonicalize_ohlcv(df_eval)
                except ValueError:
                    _FEATURE_CACHE[cache_key] = None  # negative cache
                    cache_misses += 1
                    continue
                min_days = int(cur_rules.get("history", {}).get("minimum_days", 65))
                if len(normalized) < min_days:
                    _FEATURE_CACHE[cache_key] = None
                    cache_misses += 1
                    continue
                if not has_turnover:
                    normalized = normalized.copy()
                    normalized["turnover_value"] = normalized["close"] * normalized["volume"]
                feature_dqf: list[str] = []
                feature_md: list[str] = []
                cached_features = _compute_base_features(
                    normalized, market_slice, cur_rules,
                    data_quality_flags=feature_dqf,
                    missing_data=feature_md,
                    market_index_source="unavailable",
                )
                _FEATURE_CACHE[cache_key] = cached_features
                cache_misses += 1
            else:
                cache_hits += 1

            if cached_features is None:
                continue   # negative cache — known invalid

            try:
                result = evaluate_surge_candidate(
                    stock_id,
                    stock_id,  # company_name placeholder
                    df_eval,
                    market_slice,
                    include_unfit=False,
                    precomputed_features=cached_features,
                )
            except Exception as exc:
                logger.debug("evaluate failed for %s on %s: %s", stock_id, as_of_date, exc)
                continue

            if result is None:
                continue
            if result.candidate_type not in config.target_candidate_types:
                continue

            # Phase 9.8: persist base_high/base_low/avg_volume_50 for downstream
            # dynamic Measured Move target computation in trade_simulator.
            base_high = float(cached_features.get("base_high", 0.0)) if cached_features else 0.0
            base_low = float(cached_features.get("base_low", 0.0)) if cached_features else 0.0
            avg_volume_50 = float(cached_features.get("avg_volume_50_shares", 0.0)) if cached_features else 0.0

            rows_to_persist.append({
                "run_id": config.run_id,
                "signal_date": as_of_date,
                "stock_id": stock_id,
                "candidate_type": result.candidate_type,
                "surge_candidate_score": int(result.surge_candidate_score),
                "pre_breakout_score": int(result.metrics.pre_breakout_score),
                "confidence_score": int(result.confidence_score),
                "risk_score": int(result.risk_score),
                "close_price": float(df_eval["Close"].iloc[-1]),
                "range_90d": float(result.metrics.range_90d),
                "return_60d": float(result.metrics.return_60d),
                "return_20d": float(result.metrics.return_20d),
                "volume_contraction_ratio": float(result.metrics.volume_contraction_ratio),
                "ema_spread": float(result.metrics.ema_spread),
                "sector_category": result.metrics.sector_category,
                "base_high": base_high,
                "base_low": base_low,
                "avg_volume_50": avg_volume_50,
            })
            by_type_counter[result.candidate_type] = by_type_counter.get(result.candidate_type, 0) + 1

        days_processed += 1
        if progress_callback and (day_idx % 10 == 0):
            progress_callback({"day_idx": day_idx, "total_days": len(trading_dates), "signals_so_far": len(rows_to_persist)})

    _persist_signals(db_path, rows_to_persist)

    if cache_hits + cache_misses > 0:
        logger.info("feature cache hits=%d misses=%d hit_rate=%.1f%% (size=%d)",
                    cache_hits, cache_misses,
                    100.0 * cache_hits / max(1, cache_hits + cache_misses),
                    len(_FEATURE_CACHE))

    return ReplaySummary(
        run_id=config.run_id,
        days_processed=days_processed,
        signals_generated=len(rows_to_persist),
        by_type=by_type_counter,
    )


def _slice_market_to_date(market_df: pd.DataFrame, as_of_date: str, lookback_bars: int) -> Optional[pd.DataFrame]:
    """Cut TAIEX dataframe to bars on or before as_of_date, most recent N rows."""
    if "date" in market_df.columns:
        mask = market_df["date"] <= as_of_date
        sliced = market_df[mask].tail(lookback_bars)
        return sliced if not sliced.empty else None
    # If no date column, assume index is chronological and just take last N — best-effort
    return market_df.tail(lookback_bars)


def _persist_signals(db_path: Path | str, rows: Iterable[dict]) -> int:
    rows = list(rows)
    if not rows:
        return 0
    sql = """
        INSERT OR REPLACE INTO backtest_signals
          (run_id, signal_date, stock_id, candidate_type, surge_candidate_score,
           pre_breakout_score, confidence_score, risk_score, close_price,
           range_90d, return_60d, return_20d, volume_contraction_ratio,
           ema_spread, sector_category, base_high, base_low, avg_volume_50)
        VALUES (:run_id, :signal_date, :stock_id, :candidate_type, :surge_candidate_score,
                :pre_breakout_score, :confidence_score, :risk_score, :close_price,
                :range_90d, :return_60d, :return_20d, :volume_contraction_ratio,
                :ema_spread, :sector_category, :base_high, :base_low, :avg_volume_50)
    """
    conn = sqlite3.connect(db_path)
    try:
        conn.executemany(sql, rows)
        conn.commit()
    finally:
        conn.close()
    return len(rows)


def load_signals(db_path: Path | str, run_id: str) -> pd.DataFrame:
    """Load all signals for a given run_id as a DataFrame."""
    conn = sqlite3.connect(db_path)
    try:
        df = pd.read_sql_query(
            "SELECT * FROM backtest_signals WHERE run_id = ? ORDER BY signal_date ASC, stock_id ASC",
            conn,
            params=(run_id,),
        )
    finally:
        conn.close()
    return df


def generate_run_id(prefix: str = "run") -> str:
    return f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
