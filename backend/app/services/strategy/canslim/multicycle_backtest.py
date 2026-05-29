"""Continuous fixed-param CAN SLIM multi-cycle backtest.

Phase M3 is measurement-only: it uses the default YAML configuration, PIT
universe membership, PIT fundamentals, and the existing trade simulator. It does
not optimize, grid-search, or mutate strategy parameters.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from backend.app.services.backtest.historical_data_store import CachedHistoricalDataStore, DEFAULT_DB_PATH, HistoricalDataStore
from backend.app.services.backtest.pit_fundamentals_store import CachedPitFundamentalsStore, DEFAULT_PIT_DB_PATH, PitFundamentalsStore
from backend.app.services.backtest.trade_simulator import canslim_trade_rules_from_params, load_trades, simulate_trades
from backend.app.services.strategy.canslim.attribution import aggregate_by, regime_bucket_at_entry
from backend.app.services.strategy.canslim.extension_attribution import compute_extension_metrics
from backend.app.services.strategy.canslim.params import load_params
from backend.app.services.strategy.canslim.pit_inputs import build_pit_inputs
from backend.app.services.strategy.canslim.pit_universe import get_universe_as_of
from backend.app.services.strategy.canslim.universe_source import get_delisted_universe_symbols
from backend.app.services.strategy.canslim.walk_forward import (
    _grade_at_least,
    _market_features_for_entry,
    _regime_entry_gate_blocks,
    _signal_row_from_card,
    _universe_returns_as_of,
)
from backend.app.services.strategy.canslim.observer import observe

logger = logging.getLogger(__name__)

# Calendar-day gap beyond which a symbol's last bar is treated as "no longer
# trading" (delisted/halted). Generous enough to clear the longest TW holiday
# break (Lunar New Year ~9 days). Only applied when survivorship inclusion is on.
_DELISTED_STALENESS_DAYS = 15


def _include_delisted_enabled() -> bool:
    """Opt-in survivorship correction. Default OFF so validated M3 runs are
    unchanged until the user backfills delisted OHLCV and re-validates."""
    return os.getenv("AISTOCK_INCLUDE_DELISTED", "").strip().lower() in ("1", "true", "yes", "on")


TAGGED_TRADE_COLUMNS = [
    "window",
    "segment",
    "named_cycle",
    "horizon",
    "stock_id",
    "signal_date",
    "entry_date",
    "grade",
    "regime_bucket_at_entry",
    "net_return_pct",
    "holding_days",
    "close_to_ma20",
    "pct_from_52w_high",
    "return_20d",
    "return_60d",
    "days_since_breakout",
]

DEFAULT_NAMED_CYCLES = (
    ("2011-H2-euro", "2011-07-01", "2011-12-31"),
    ("2015-H2-correction", "2015-07-01", "2015-12-31"),
    ("2018-Q4-selloff", "2018-10-01", "2018-12-31"),
    ("2020-COVID", "2020-02-01", "2020-06-30"),
    ("2022-bear", "2022-01-01", "2022-12-31"),
    ("2023-24-bull", "2023-01-01", "2024-12-31"),
)


@dataclass(frozen=True)
class MulticycleReport:
    run_id: str
    start_date: str
    end_date: str
    cadence_days: int
    candidate_symbols: int
    years: list[dict[str, Any]]
    summary: dict[str, Any]
    tagged_trades_csv: str
    summary_json: str
    summary_md: str


def cadence_grid(store: HistoricalDataStore, start_date: str, end_date: str, *, cadence_days: int = 5) -> list[str]:
    """Return every Nth trading date in [start_date, end_date]."""
    if cadence_days < 1:
        raise ValueError("cadence_days must be >= 1")
    dates = store.get_all_trading_dates(start_date, end_date)
    return dates[::cadence_days]


def year_ranges(start_date: str, end_date: str) -> list[tuple[int, str, str]]:
    start_year = int(start_date[:4])
    end_year = int(end_date[:4])
    ranges = []
    for year in range(start_year, end_year + 1):
        ranges.append((year, max(start_date, f"{year}-01-01"), min(end_date, f"{year}-12-31")))
    return ranges


def fundamentals_covered_symbols(
    pit_db_path: Path | str = DEFAULT_PIT_DB_PATH,
    *,
    tables: Iterable[str] = ("month_revenue", "institutional", "margin", "per", "financials"),
) -> list[str]:
    """Return symbols with any PIT fundamentals/chip coverage."""
    allowed = {"month_revenue", "institutional", "margin", "per", "financials"}
    selected_tables = [table for table in tables if table in allowed]
    symbols: set[str] = set()
    conn = sqlite3.connect(pit_db_path)
    try:
        for table in selected_tables:
            try:
                rows = conn.execute(f"SELECT DISTINCT stock_id FROM {table}").fetchall()
            except sqlite3.OperationalError:
                continue
            symbols.update(str(row[0]) for row in rows if row[0])
    finally:
        conn.close()
    return sorted(symbols)


def run_multicycle_backtest(
    *,
    run_id: str = "canslim_multicycle_v1",
    ohlcv_db_path: Path | str = DEFAULT_DB_PATH,
    pit_db_path: Path | str = DEFAULT_PIT_DB_PATH,
    start_date: str = "2011-01-01",
    end_date: str = "2025-12-31",
    cadence_days: int = 5,
    output_dir: Path | str = "artifacts/canslim_multicycle",
    turnover_floor: float | None = None,
    candidate_symbols: list[str] | None = None,
    resume: bool = True,
) -> MulticycleReport:
    """Run the continuous fixed-param M3 backtest and write tagged trades."""
    started = time.time()
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    year_dir = out_dir / "years"
    year_dir.mkdir(parents=True, exist_ok=True)
    db_path = out_dir / f"{run_id}.db"
    csv_path = out_dir / "multicycle_tagged_trades.csv"
    json_path = out_dir / "multicycle_summary.json"
    md_path = out_dir / "multicycle_summary.md"

    candidates = candidate_symbols or fundamentals_covered_symbols(pit_db_path)
    staleness_days: int | None = None
    if _include_delisted_enabled():
        delisted = [s for s in get_delisted_universe_symbols() if s not in set(candidates)]
        candidates = [*candidates, *delisted]
        staleness_days = _DELISTED_STALENESS_DAYS
        logger.info("Survivorship correction ON: +%d delisted candidates, staleness=%dd", len(delisted), staleness_days)
    logger.info("M3 fixed-param run %s: %d candidate symbols", run_id, len(candidates))
    data_store = CachedHistoricalDataStore(
        ohlcv_db_path,
        universe=[*candidates, "TAIEX", "TPEX"],
        start_date=start_date,
        end_date=end_date,
        lookback_buffer_days=500,
        forward_buffer_days=180,
    )
    pit_store = CachedPitFundamentalsStore(pit_db_path, universe=candidates)

    year_reports: list[dict[str, Any]] = []
    year_frames: list[pd.DataFrame] = []
    for year, year_start, year_end in year_ranges(start_date, end_date):
        year_csv = year_dir / f"{year}.csv"
        if resume and year_csv.exists():
            logger.info("Skipping completed year %s: %s", year, year_csv)
            frame = pd.read_csv(year_csv)
            year_frames.append(_ensure_tagged_columns(frame))
            year_reports.append({"year": year, "status": "skipped", "trades": int(len(frame))})
            continue
        logger.info("Running year %s (%s to %s)", year, year_start, year_end)
        frame, diagnostics = _run_year(
            run_id=f"{run_id}_{year}",
            year=year,
            start_date=year_start,
            end_date=year_end,
            cadence_days=cadence_days,
            candidate_symbols=candidates,
            data_store=data_store,
            pit_store=pit_store,
            db_path=db_path,
            turnover_floor=turnover_floor,
            max_staleness_days=staleness_days,
        )
        frame = _ensure_tagged_columns(frame)
        frame.to_csv(year_csv, index=False, encoding="utf-8-sig")
        year_frames.append(frame)
        year_reports.append({"year": year, "status": "completed", "trades": int(len(frame)), **diagnostics})

    all_trades = pd.concat(year_frames, ignore_index=True) if year_frames else empty_tagged_trades()
    all_trades = _ensure_tagged_columns(all_trades)
    all_trades.to_csv(csv_path, index=False, encoding="utf-8-sig")
    summary = summarize_multicycle(all_trades)
    summary["elapsed_seconds"] = round(time.time() - started, 1)
    report = MulticycleReport(
        run_id=run_id,
        start_date=start_date,
        end_date=end_date,
        cadence_days=cadence_days,
        candidate_symbols=len(candidates),
        years=year_reports,
        summary=summary,
        tagged_trades_csv=str(csv_path),
        summary_json=str(json_path),
        summary_md=str(md_path),
    )
    _write_report(report, json_path, md_path)
    return report


def _run_year(
    *,
    run_id: str,
    year: int,
    start_date: str,
    end_date: str,
    cadence_days: int,
    candidate_symbols: list[str],
    data_store,
    pit_store,
    db_path: Path,
    turnover_floor: float | None,
    max_staleness_days: int | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    params = load_params()
    canslim_cfg = params["backtest"]["canslim"]
    horizon = str(canslim_cfg.get("horizon", "swing_term"))
    min_grade = str(canslim_cfg.get("min_entry_grade", "B"))
    regime_entry_gate = bool(canslim_cfg.get("regime_entry_gate", True))
    signal_rows: list[dict[str, Any]] = []
    dates = cadence_grid(data_store, start_date, end_date, cadence_days=cadence_days)
    returns_cache: dict[tuple[str, int], dict[str, float]] = {}
    market_cache = {}
    evaluated = 0
    selected_total = 0
    signals_before_gate = 0
    gate_removed = 0

    for idx, as_of_date in enumerate(dates, start=1):
        tradable = get_universe_as_of(
            as_of_date,
            data_store,
            turnover_floor=turnover_floor,
            candidate_symbols=candidate_symbols,
            max_staleness_days=max_staleness_days,
        )
        selected_total += len(tradable)
        if idx == 1 or idx % 25 == 0:
            logger.info("%s %s/%s: %s tradable symbols", year, idx, len(dates), len(tradable))
        if not tradable:
            continue
        market_features = _market_features_for_entry(
            as_of_date,
            market=None,
            data_store=data_store,
            universe=tradable,
            cache=market_cache,
        )
        returns_60d = returns_cache.setdefault((as_of_date, 60), _universe_returns_as_of(data_store, tradable, as_of_date, 60))
        returns_252d = returns_cache.setdefault((as_of_date, 252), _universe_returns_as_of(data_store, tradable, as_of_date, 252))
        for stock_id in tradable:
            evaluated += 1
            bars = data_store.get_ohlcv_as_of(stock_id, as_of_date, 280)
            if len(bars) < 65:
                continue
            detail, fin_metrics, eps_filing_date = build_pit_inputs(stock_id, as_of_date, pit_store)
            cards = observe(
                stock_id,
                as_of_date,
                store=data_store,
                market=market_features,
                fin_metrics=fin_metrics,
                detail=detail,
                universe_returns_60d=returns_60d,
                universe_returns_252d=returns_252d,
                event_window_active=False,
                eps_filing_date=eps_filing_date,
            )
            card = cards[horizon]
            grade = str(card.scores.get("grade", "C"))
            if bool(card.scores.get("hard_blocked", False)) or not _grade_at_least(grade, min_grade):
                continue
            signals_before_gate += 1
            if _regime_entry_gate_blocks(horizon, grade, market_features, params, enabled=regime_entry_gate):
                gate_removed += 1
                continue
            signal_rows.append(_signal_row_from_card(run_id, stock_id, as_of_date, bars, horizon, card))

    signals = pd.DataFrame(signal_rows)
    if signals.empty:
        return empty_tagged_trades(), {
            "cadence_dates": len(dates),
            "avg_tradable_symbols": round(selected_total / len(dates), 2) if dates else 0.0,
            "evaluated": evaluated,
            "signals": 0,
            "gate_removed": gate_removed,
        }
    simulate_trades(
        signals_df=signals,
        data_store=data_store,
        rules=canslim_trade_rules_from_params(),
        run_id=run_id,
        db_path=db_path,
    )
    trades = load_trades(db_path, run_id)
    tagged = tag_multicycle_trades(
        segment=f"year_{year}",
        horizon=horizon,
        signals=signals,
        trades=trades,
        data_store=data_store,
        stock_universe=candidate_symbols,
    )
    return tagged, {
        "cadence_dates": len(dates),
        "avg_tradable_symbols": round(selected_total / len(dates), 2) if dates else 0.0,
        "evaluated": evaluated,
        "signals": int(len(signals)),
        "signals_before_gate": signals_before_gate,
        "gate_removed": gate_removed,
    }


def tag_multicycle_trades(
    *,
    segment: str,
    horizon: str,
    signals: pd.DataFrame,
    trades: pd.DataFrame,
    data_store,
    stock_universe: list[str],
) -> pd.DataFrame:
    if trades.empty or signals.empty:
        return empty_tagged_trades()
    filled = trades[trades["entry_status"] == "filled"].copy()
    if filled.empty:
        return empty_tagged_trades()
    signal_cols = ["stock_id", "signal_date", "canslim_grade", "canslim_horizon"]
    merged = filled.merge(signals[signal_cols], on=["stock_id", "signal_date"], how="left")
    rows: list[dict[str, Any]] = []
    regime_cache: dict[str, str] = {}
    extension_cache: dict[tuple[str, str], dict[str, Any]] = {}
    for row in merged.to_dict("records"):
        entry_date = str(row.get("entry_date") or "")
        stock_id = str(row.get("stock_id"))
        if entry_date not in regime_cache:
            regime_cache[entry_date] = regime_bucket_at_entry(entry_date, data_store, stock_universe)
        ext_key = (stock_id, entry_date)
        if ext_key not in extension_cache:
            extension_cache[ext_key] = compute_extension_metrics(data_store, stock_id, entry_date)
        item = {
            "window": segment,
            "segment": segment,
            "named_cycle": named_cycle_for_date(entry_date),
            "horizon": row.get("canslim_horizon") or horizon,
            "stock_id": stock_id,
            "signal_date": row.get("signal_date"),
            "entry_date": entry_date,
            "grade": str(row.get("canslim_grade") or "unknown"),
            "regime_bucket_at_entry": regime_cache[entry_date],
            "net_return_pct": float(row.get("net_return_pct") or 0.0),
            "holding_days": int(row.get("hold_days") or 0),
        }
        item.update(extension_cache[ext_key])
        rows.append(item)
    return _ensure_tagged_columns(pd.DataFrame(rows))


def named_cycle_for_date(date_str: str) -> str:
    for name, start, end in DEFAULT_NAMED_CYCLES:
        if start <= date_str <= end:
            return name
    return "other"


def summarize_multicycle(trades: pd.DataFrame) -> dict[str, Any]:
    if trades.empty:
        return {"n_trades": 0, "by_grade_regime": [], "by_regime": [], "by_named_cycle": []}
    return {
        "n_trades": int(len(trades)),
        "by_grade_regime": aggregate_by(trades, ["grade", "regime_bucket_at_entry"]),
        "by_regime": aggregate_by(trades, ["regime_bucket_at_entry"]),
        "by_named_cycle": aggregate_by(trades, ["named_cycle"]),
        "by_segment": aggregate_by(trades, ["segment"]),
    }


def empty_tagged_trades() -> pd.DataFrame:
    return pd.DataFrame(columns=TAGGED_TRADE_COLUMNS)


def _ensure_tagged_columns(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    for column in TAGGED_TRADE_COLUMNS:
        if column not in out.columns:
            out[column] = pd.NA
    return out[TAGGED_TRADE_COLUMNS]


def _write_report(report: MulticycleReport, json_path: Path, md_path: Path) -> None:
    payload = {
        "run_id": report.run_id,
        "start_date": report.start_date,
        "end_date": report.end_date,
        "cadence_days": report.cadence_days,
        "candidate_symbols": report.candidate_symbols,
        "years": report.years,
        "summary": report.summary,
        "tagged_trades_csv": report.tagged_trades_csv,
    }
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = [
        f"# CAN SLIM Multicycle Backtest: {report.run_id}",
        "",
        f"Period: {report.start_date} to {report.end_date}",
        f"Cadence days: {report.cadence_days}",
        f"Candidate symbols: {report.candidate_symbols}",
        f"Tagged trades CSV: `{report.tagged_trades_csv}`",
        f"Total trades: {report.summary.get('n_trades', 0)}",
        "",
        "## Years",
    ]
    for year in report.years:
        lines.append(f"- {year['year']}: {year['status']}, trades={year.get('trades', 0)}, signals={year.get('signals', 'n/a')}")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
