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
from typing import Any, Iterable, Optional

import pandas as pd

from backend.app.services.backtest.historical_data_store import HistoricalDataStore
from backend.app.services.screener_rules import load_surge_candidate_rules
from backend.app.services.screener_service import (
    _canonicalize_ohlcv,
    _compute_base_features,
    evaluate_surge_candidate,
)
from backend.app.services.strategy.canslim.observer import observe as observe_canslim
from backend.app.services.strategy.canslim.params import load_params as load_canslim_params
from backend.app.services.strategy.canslim.types import MarketFeatures

logger = logging.getLogger(__name__)

CANSLIM_CANDIDATE_TYPE = "CANSLIM觀察"


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
    return_90d REAL,
    avg_turnover_20 REAL,
    base_range_pct REAL,
    volume_today_shares REAL,
    close_to_base_high_ratio REAL,
    ema5_slope REAL,
    ema10_slope REAL,
    ema20_slope REAL,
    ema_micro_upturn_score INTEGER,
    base_compression_score INTEGER,
    ema_down_to_up_transition_score INTEGER,
    trend_template_ok INTEGER,
    entry_tier INTEGER DEFAULT 0,
    canslim_horizon TEXT,
    canslim_grade TEXT,
    canslim_signal_raw INTEGER,
    canslim_signal_achievable_max INTEGER,
    atr20 REAL,
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
    for col, typ in (
        ("base_high", "REAL"),
        ("base_low", "REAL"),
        ("avg_volume_50", "REAL"),
        ("return_90d", "REAL"),
        ("avg_turnover_20", "REAL"),
        ("base_range_pct", "REAL"),
        ("volume_today_shares", "REAL"),
        ("close_to_base_high_ratio", "REAL"),
        ("ema5_slope", "REAL"),
        ("ema10_slope", "REAL"),
        ("ema20_slope", "REAL"),
        ("ema_micro_upturn_score", "INTEGER"),
        ("base_compression_score", "INTEGER"),
        ("ema_down_to_up_transition_score", "INTEGER"),
        ("trend_template_ok", "INTEGER"),
        ("entry_tier", "INTEGER DEFAULT 0"),
        ("canslim_horizon", "TEXT"),
        ("canslim_grade", "TEXT"),
        ("canslim_signal_raw", "INTEGER"),
        ("canslim_signal_achievable_max", "INTEGER"),
        ("atr20", "REAL"),
    ):
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
    lookback_bars: int = 220   # enough bars for Phase 11 EMA200 Trend Template
    market_df: Optional[pd.DataFrame] = None  # TAIEX history for RS computation
    canslim_fin_metrics_by_stock: dict[str, dict] = field(default_factory=dict)
    canslim_detail_by_stock: dict[str, dict] = field(default_factory=dict)
    canslim_market: MarketFeatures | dict | None = None
    canslim_universe_returns_60d: dict[str, float] | None = None
    canslim_universe_returns_252d: dict[str, float] | None = None
    canslim_eps_filing_dates_by_stock: dict[str, str] = field(default_factory=dict)
    canslim_event_window_by_stock: dict[str, bool] = field(default_factory=dict)


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

_FEATURE_CACHE: dict[tuple[str, int, str, str], Optional[dict]] = {}


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


_SCHEMA_INITIALIZED: set[str] = set()


def initialize_replay_schema(db_path: Path | str) -> None:
    # Phase 9.8: skip if already done in this process (called per trial otherwise).
    key = str(Path(db_path).resolve())
    if key in _SCHEMA_INITIALIZED:
        return
    conn = sqlite3.connect(db_path)
    try:
        # Phase 9.8 speedup: WAL + relaxed sync for concurrent worker writes.
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript(_SCHEMA_SQL)
        _migrate_signals_schema(conn)
        conn.commit()
    finally:
        conn.close()
    _SCHEMA_INITIALIZED.add(key)


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
    wants_canslim = CANSLIM_CANDIDATE_TYPE in config.target_candidate_types
    wants_legacy = any(candidate_type != CANSLIM_CANDIDATE_TYPE for candidate_type in config.target_candidate_types)
    canslim_params = load_canslim_params() if wants_canslim else None
    canslim_cfg = canslim_params["backtest"]["canslim"] if canslim_params else {}
    canslim_horizon = str(canslim_cfg.get("horizon", "swing_term"))
    canslim_min_grade = str(canslim_cfg.get("min_entry_grade", "B"))

    # Resolve cache namespace ONCE for this session — the shape rules don't
    # change between trials, so this hash is constant for the whole replay.
    cur_rules = load_surge_candidate_rules()
    namespace = _cache_namespace(cur_rules)

    # ── Fast-fail pre-filter ──────────────────────────────────────────────
    # Phase 11 keeps this intentionally loose: only immutable Flat Base entry
    # structure is checked here. Quality gates are handled by entry_tier and
    # position sizing after evaluate_surge_candidate computes scores.
    pre_filter_active = wants_legacy and (
        len(config.target_candidate_types) == 1
        and "起漲前觀察" in config.target_candidate_types
    )
    pp = cur_rules.get("price_position", {})
    em = cur_rules.get("ema", {})
    vol = cur_rules.get("volume", {})
    cls = cur_rules.get("classification", {})
    pf_range_min = max(float(pp.get("pre_breakout_range_90d_min", 0.10)), 0.10)
    pf_range_max = min(float(pp.get("pre_breakout_range_90d_max", 0.30)), 0.30)
    pf_return_90d_min = -0.25
    pf_ema_spread_max = 0.08
    pf_vol_contraction_max = min(float(vol.get("pre_breakout_volume_contraction_max", 1.0)), 1.0)
    pf_close_to_base_high_max = 1.08
    pf_turnover_min = 30_000_000.0
    pf_breakout_buffer = float(cls.get("breakout_pivot_buffer", 0.001))

    cache_hits = 0
    cache_misses = 0
    pre_filter_skipped = 0

    for day_idx, as_of_date in enumerate(trading_dates):
        # Point-in-time market frame (TAIEX up to this date)
        market_slice = None
        if config.market_df is not None and not config.market_df.empty:
            market_slice = _slice_market_to_date(config.market_df, as_of_date, config.lookback_bars)

        for stock_id in config.stock_universe:
            df_hist = data_store.get_ohlcv_as_of(stock_id, as_of_date, config.lookback_bars)
            if len(df_hist) < 65:   # need history.minimum_days
                continue

            if wants_canslim:
                canslim_row = _build_canslim_signal_row(
                    config,
                    stock_id,
                    as_of_date,
                    df_hist,
                    canslim_horizon,
                    canslim_min_grade,
                )
                if canslim_row is not None:
                    rows_to_persist.append(canslim_row)
                    by_type_counter[CANSLIM_CANDIDATE_TYPE] = by_type_counter.get(CANSLIM_CANDIDATE_TYPE, 0) + 1

            if not wants_legacy:
                continue

            # Rename columns to PascalCase (evaluate_surge_candidate's _canonicalize_ohlcv expects this)
            df_eval = df_hist.rename(
                columns={"open": "Open", "high": "High", "low": "Low",
                         "close": "Close", "volume": "Volume", "turnover": "Turnover"}
            )

            # ── Feature cache lookup ────────────────────────────────────
            cache_key = (namespace, config.lookback_bars, stock_id, as_of_date)
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

            # ── Phase 9.8.1 fast-fail: skip full evaluate when basic 起漲前觀察 ──
            # ── gates fail. Saves ~5-7 ms on 80-90% of (date, stock) pairs. ─────
            if pre_filter_active:
                r90 = cached_features.get("range_90d", 0.0)
                if not (pf_range_min <= r90 <= pf_range_max):
                    pre_filter_skipped += 1
                    continue
                r90d = cached_features.get("return_90d", 0.0)
                if r90d < pf_return_90d_min:
                    pre_filter_skipped += 1
                    continue
                es = cached_features.get("ema_spread", 1.0)
                if es > pf_ema_spread_max:
                    pre_filter_skipped += 1
                    continue
                vcr = cached_features.get("volume_contraction_ratio", 1.0)
                if vcr > pf_vol_contraction_max:
                    pre_filter_skipped += 1
                    continue
                ctbh = cached_features.get("close_to_base_high_ratio", 0.0)
                # close_to_base_high too high = already extended past buy zone
                if ctbh > pf_close_to_base_high_max:
                    pre_filter_skipped += 1
                    continue
                close_today = cached_features.get("close_today", 0.0)
                base_high = cached_features.get("base_high", 0.0)
                if base_high <= 0 or close_today <= base_high * (1.0 + pf_breakout_buffer):
                    pre_filter_skipped += 1
                    continue
                avg_turnover_20 = cached_features.get("avg_turnover_20", 0.0)
                if avg_turnover_20 < pf_turnover_min:
                    pre_filter_skipped += 1
                    continue

            try:
                result = evaluate_surge_candidate(
                    stock_id,
                    stock_id,  # company_name placeholder
                    df_eval,
                    market_slice,
                    include_unfit=pre_filter_active,
                    precomputed_features=cached_features,
                )
            except Exception as exc:
                logger.debug("evaluate failed for %s on %s: %s", stock_id, as_of_date, exc)
                continue

            if result is None:
                continue
            entry_tier = int(getattr(result.metrics, "entry_tier", 0) or 0)
            tiered_entry_match = (
                entry_tier > 0
                and "起漲前觀察" in config.target_candidate_types
            )
            if result.candidate_type not in config.target_candidate_types and not tiered_entry_match:
                continue
            row_candidate_type = (
                result.candidate_type
                if result.candidate_type != "不符合"
                else "起漲前觀察"
            )

            # Phase 9.8: persist base_high/base_low/avg_volume_50 for downstream
            # dynamic Measured Move target computation in trade_simulator.
            base_high = float(cached_features.get("base_high", 0.0)) if cached_features else 0.0
            base_low = float(cached_features.get("base_low", 0.0)) if cached_features else 0.0
            avg_volume_50 = float(cached_features.get("avg_volume_50_shares", 0.0)) if cached_features else 0.0
            volume_today_shares = float(cached_features.get("volume_today_shares", 0.0)) if cached_features else 0.0

            rows_to_persist.append({
                "run_id": config.run_id,
                "signal_date": as_of_date,
                "stock_id": stock_id,
                "candidate_type": row_candidate_type,
                "surge_candidate_score": int(result.surge_candidate_score),
                "pre_breakout_score": int(result.metrics.pre_breakout_score),
                "confidence_score": int(result.confidence_score),
                "risk_score": int(result.risk_score),
                "close_price": float(df_eval["Close"].iloc[-1]),
                "range_90d": float(result.metrics.range_90d),
                "return_60d": float(result.metrics.return_60d),
                "return_90d": float(result.metrics.return_90d),
                "return_20d": float(result.metrics.return_20d),
                "volume_contraction_ratio": float(result.metrics.volume_contraction_ratio),
                "ema_spread": float(result.metrics.ema_spread),
                "sector_category": result.metrics.sector_category,
                "base_high": base_high,
                "base_low": base_low,
                "avg_volume_50": avg_volume_50,
                "avg_turnover_20": float(result.metrics.avg_turnover_20),
                "base_range_pct": float(result.metrics.base_range_pct),
                "volume_today_shares": volume_today_shares,
                "close_to_base_high_ratio": float(result.metrics.close_to_base_high_ratio),
                "ema5_slope": float(result.metrics.ema5_slope),
                "ema10_slope": float(result.metrics.ema10_slope),
                "ema20_slope": float(result.metrics.ema20_slope),
                "ema_micro_upturn_score": int(result.metrics.ema_micro_upturn_score),
                "base_compression_score": int(result.scores.base_compression_score),
                "ema_down_to_up_transition_score": int(result.metrics.ema_down_to_up_transition_score),
                "trend_template_ok": int(bool(cached_features.get("trend_template_ok", False))) if cached_features else 0,
                "entry_tier": entry_tier,
                "canslim_horizon": None,
                "canslim_grade": None,
                "canslim_signal_raw": None,
                "canslim_signal_achievable_max": None,
                "atr20": _atr20(df_hist),
            })
            by_type_counter[row_candidate_type] = by_type_counter.get(row_candidate_type, 0) + 1

        days_processed += 1
        if progress_callback and (day_idx % 10 == 0):
            progress_callback({"day_idx": day_idx, "total_days": len(trading_dates), "signals_so_far": len(rows_to_persist)})

    _persist_signals(db_path, rows_to_persist)

    if cache_hits + cache_misses > 0:
        logger.info("feature cache hits=%d misses=%d hit_rate=%.1f%% (size=%d) "
                    "pre_filter_skipped=%d (saved %.1f%% of evaluate calls)",
                    cache_hits, cache_misses,
                    100.0 * cache_hits / max(1, cache_hits + cache_misses),
                    len(_FEATURE_CACHE),
                    pre_filter_skipped,
                    100.0 * pre_filter_skipped / max(1, cache_hits + cache_misses))

    summary = ReplaySummary(
        run_id=config.run_id,
        days_processed=days_processed,
        signals_generated=len(rows_to_persist),
        by_type=by_type_counter,
    )
    # Phase 9.8 speedup: also return rows so caller can skip a load_signals DB read.
    summary.signal_rows = rows_to_persist  # type: ignore[attr-defined]
    return summary


def _build_canslim_signal_row(
    config: ReplayConfig,
    stock_id: str,
    as_of_date: str,
    df_hist: pd.DataFrame,
    horizon: str,
    min_grade: str,
) -> dict | None:
    try:
        cards = observe_canslim(
            stock_id,
            as_of_date,
            store=_ReplayStoreAdapter(stock_id, df_hist),
            market=config.canslim_market or MarketFeatures(),
            fin_metrics=config.canslim_fin_metrics_by_stock.get(stock_id),
            detail=config.canslim_detail_by_stock.get(stock_id),
            universe_returns_60d=config.canslim_universe_returns_60d,
            universe_returns_252d=config.canslim_universe_returns_252d,
            event_window_active=config.canslim_event_window_by_stock.get(stock_id, False),
            eps_filing_date=config.canslim_eps_filing_dates_by_stock.get(stock_id),
        )
    except Exception as exc:
        logger.debug("CANSLIM observe failed for %s on %s: %s", stock_id, as_of_date, exc)
        return None

    card = cards.get(horizon)
    if card is None:
        return None
    grade = str(card.scores.get("grade", "C"))
    if bool(card.scores.get("hard_blocked", False)) or not _grade_at_least(grade, min_grade):
        return None

    latest = df_hist.iloc[-1]
    base_high = _tail_float(df_hist["high"], 20, "max")
    base_low = _tail_float(df_hist["low"], 20, "min")
    avg_volume_50 = _tail_float(df_hist["volume"], 50, "mean")
    close = float(latest["close"])
    return {
        "run_id": config.run_id,
        "signal_date": as_of_date,
        "stock_id": stock_id,
        "candidate_type": CANSLIM_CANDIDATE_TYPE,
        "surge_candidate_score": int(card.scores.get("signal", 0) or 0),
        "pre_breakout_score": int(card.scores.get("signal", 0) or 0),
        "confidence_score": int(card.scores.get("confidence", 0) or 0),
        "risk_score": int(card.scores.get("risk", 0) or 0),
        "close_price": close,
        "range_90d": _range_pct(df_hist.tail(90)),
        "return_60d": _return_pct(df_hist["close"], 60),
        "return_90d": _return_pct(df_hist["close"], 90),
        "return_20d": _return_pct(df_hist["close"], 20),
        "volume_contraction_ratio": 0.0,
        "ema_spread": 0.0,
        "sector_category": None,
        "base_high": base_high,
        "base_low": base_low,
        "avg_volume_50": avg_volume_50,
        "avg_turnover_20": _tail_float(df_hist["turnover"], 20, "mean") if "turnover" in df_hist else 0.0,
        "base_range_pct": ((base_high - base_low) / base_low) if base_low else 0.0,
        "volume_today_shares": float(latest["volume"]),
        "close_to_base_high_ratio": (close / base_high) if base_high else 0.0,
        "ema5_slope": 0.0,
        "ema10_slope": 0.0,
        "ema20_slope": 0.0,
        "ema_micro_upturn_score": 0,
        "base_compression_score": 0,
        "ema_down_to_up_transition_score": 0,
        "trend_template_ok": 0,
        "entry_tier": 0,
        "canslim_horizon": horizon,
        "canslim_grade": grade,
        "canslim_signal_raw": int(card.scores.get("signal_raw", 0) or 0),
        "canslim_signal_achievable_max": int(card.scores.get("signal_achievable_max", 0) or 0),
        "atr20": _atr20(df_hist),
    }


class _ReplayStoreAdapter:
    def __init__(self, stock_id: str, df_hist: pd.DataFrame) -> None:
        self.stock_id = stock_id
        self.df_hist = df_hist

    def get_ohlcv_as_of(self, stock_id: str, as_of_date: str, lookback_bars: int) -> pd.DataFrame:
        if stock_id != self.stock_id:
            return pd.DataFrame(columns=self.df_hist.columns)
        filtered = self.df_hist[self.df_hist["date"] <= as_of_date]
        return filtered.tail(lookback_bars).reset_index(drop=True)


def _grade_at_least(grade: str, minimum: str) -> bool:
    rank = {"C": 0, "B": 1, "A": 2, "S": 3}
    return rank.get(grade, -1) >= rank.get(minimum, 1)


def _tail_float(series: pd.Series, length: int, op: str) -> float:
    values = pd.to_numeric(series.tail(length), errors="coerce").dropna()
    if values.empty:
        return 0.0
    if op == "max":
        return float(values.max())
    if op == "min":
        return float(values.min())
    return float(values.mean())


def _return_pct(close: pd.Series, lookback: int) -> float:
    values = pd.to_numeric(close, errors="coerce").dropna()
    if len(values) <= lookback:
        return 0.0
    prior = float(values.iloc[-lookback - 1])
    return (float(values.iloc[-1]) - prior) / prior if prior else 0.0


def _range_pct(frame: pd.DataFrame) -> float:
    if frame.empty:
        return 0.0
    high = float(pd.to_numeric(frame["high"], errors="coerce").max())
    low = float(pd.to_numeric(frame["low"], errors="coerce").min())
    return (high - low) / low if low else 0.0


def _atr20(frame: pd.DataFrame) -> float:
    if len(frame) < 21:
        return 0.0
    bars = frame.tail(21).reset_index(drop=True)
    true_ranges = []
    for idx in range(1, len(bars)):
        high = float(bars.loc[idx, "high"])
        low = float(bars.loc[idx, "low"])
        prev_close = float(bars.loc[idx - 1, "close"])
        true_ranges.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    return float(sum(true_ranges[-20:]) / 20) if true_ranges else 0.0


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
           ema_spread, sector_category, base_high, base_low, avg_volume_50,
           return_90d, avg_turnover_20, base_range_pct, volume_today_shares,
           close_to_base_high_ratio, ema5_slope, ema10_slope, ema20_slope,
           ema_micro_upturn_score, base_compression_score,
           ema_down_to_up_transition_score, trend_template_ok,
           entry_tier, canslim_horizon, canslim_grade, canslim_signal_raw,
           canslim_signal_achievable_max, atr20)
        VALUES (:run_id, :signal_date, :stock_id, :candidate_type, :surge_candidate_score,
                :pre_breakout_score, :confidence_score, :risk_score, :close_price,
                :range_90d, :return_60d, :return_20d, :volume_contraction_ratio,
                :ema_spread, :sector_category, :base_high, :base_low, :avg_volume_50,
                :return_90d, :avg_turnover_20, :base_range_pct, :volume_today_shares,
                :close_to_base_high_ratio, :ema5_slope, :ema10_slope, :ema20_slope,
                :ema_micro_upturn_score, :base_compression_score,
                :ema_down_to_up_transition_score, :trend_template_ok,
                :entry_tier, :canslim_horizon, :canslim_grade, :canslim_signal_raw,
                :canslim_signal_achievable_max, :atr20)
    """
    conn = sqlite3.connect(db_path)
    try:
        # WAL was set at schema init; reapply synchronous=NORMAL on this conn
        # so this write also benefits.
        conn.execute("PRAGMA synchronous=NORMAL")
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
