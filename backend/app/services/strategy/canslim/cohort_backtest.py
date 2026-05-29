"""Forward-return cohort backtest of the CANSLIM screening (measurement only).

Validates the SCREENER (not a trading system): on each as_of date we screen the
point-in-time universe, bucket each stock by its screening verdict (pass_status /
grade / per-pillar), then measure that stock's FORWARD return over fixed horizons
(1/3/6/12 months) and compare PASS vs WATCHLIST vs the universe baseline + TAIEX.

This does NOT change any signal/score/grade math. The screening reads only data
<= as_of (PIT-safe); forward bars are used ONLY to measure outcomes, never fed back
into the screening. Fixed params, no tuning — this is measurement, not optimization.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from backend.app.services.backtest.historical_data_store import (
    CachedHistoricalDataStore,
    DEFAULT_DB_PATH,
    HistoricalDataStore,
)
from backend.app.services.backtest.pit_fundamentals_store import (
    CachedPitFundamentalsStore,
    DEFAULT_PIT_DB_PATH,
    PitFundamentalsStore,
)
from backend.app.services.strategy.canslim.canslim_output import build_full_result
from backend.app.services.strategy.canslim.multicycle_backtest import cadence_grid, fundamentals_covered_symbols
from backend.app.services.strategy.canslim.params import load_params
from backend.app.services.strategy.canslim.pit_inputs import build_pit_inputs, universe_shares_as_of
from backend.app.services.strategy.canslim.pit_universe import get_universe_as_of
from backend.app.services.strategy.canslim.screening import build_screening_result
from backend.app.services.strategy.canslim.walk_forward import (
    _market_features_for_entry,
    _universe_returns_as_of,
)

logger = logging.getLogger(__name__)

# horizon label -> forward trading-day count
HORIZONS: dict[str, int] = {"1m": 20, "3m": 60, "6m": 120, "12m": 252}
_MAX_HORIZON = max(HORIZONS.values())
PILLARS = ("C", "A", "N", "S", "L", "I", "M")


@dataclass
class CohortReport:
    run_id: str
    start_date: str
    end_date: str
    cadence_days: int
    candidate_symbols: int
    n_rows: int
    n_dates: int
    summary: dict[str, Any]
    rows_csv: str
    summary_json: str
    summary_md: str
    elapsed_seconds: float = 0.0


def forward_returns_for(store, symbol: str, as_of_date: str) -> dict[str, Any] | None:
    """Forward returns at each horizon + 12m max run-up / max drawdown.

    Entry close = last bar on/before as_of; forward bars = strictly after as_of.
    Returns None if there is no entry bar. Individual horizons are None when there
    are not yet that many forward bars (near the data end) — never fabricated.
    """
    entry_bars = store.get_ohlcv_as_of(symbol, as_of_date, 1)
    if entry_bars is None or entry_bars.empty:
        return None
    entry_close = float(entry_bars["close"].iloc[-1])
    if entry_close <= 0:
        return None
    end = (pd.Timestamp(as_of_date) + pd.Timedelta(days=int(_MAX_HORIZON * 1.8) + 15)).strftime("%Y-%m-%d")
    fwd = store.get_ohlcv(symbol, as_of_date, end)
    if fwd is not None and not fwd.empty:
        fwd = fwd[fwd["date"] > as_of_date].reset_index(drop=True)
    out: dict[str, Any] = {}
    n_fwd = 0 if fwd is None else len(fwd)
    for name, bars in HORIZONS.items():
        if n_fwd >= bars:
            fwd_close = float(fwd["close"].iloc[bars - 1])
            out[f"fwd_{name}"] = round(fwd_close / entry_close - 1.0, 6) if fwd_close > 0 else None
        else:
            out[f"fwd_{name}"] = None
    if n_fwd > 0:
        window = fwd.head(_MAX_HORIZON)
        high = pd.to_numeric(window["high"], errors="coerce").max()
        low = pd.to_numeric(window["low"], errors="coerce").min()
        out["max_runup_12m"] = round(float(high) / entry_close - 1.0, 6) if pd.notna(high) else None
        out["max_dd_12m"] = round(float(low) / entry_close - 1.0, 6) if pd.notna(low) else None
    else:
        out["max_runup_12m"] = None
        out["max_dd_12m"] = None
    return out


def _cohort_rows(
    data_store,
    pit_store,
    params,
    candidates: list[str],
    dates: list[str],
    *,
    turnover_floor: float | None = None,
    max_staleness_days: int | None = None,
) -> pd.DataFrame:
    """Screen the PIT universe at each date and attach forward returns. Pure over the
    injected stores so it can be unit-tested without the Cached layer."""
    market_cache: dict[str, Any] = {}
    taiex_cache: dict[str, dict[str, Any] | None] = {}
    rows: list[dict[str, Any]] = []
    for idx, as_of in enumerate(dates, start=1):
        universe = get_universe_as_of(
            as_of, data_store, turnover_floor=turnover_floor,
            candidate_symbols=candidates, max_staleness_days=max_staleness_days,
        )
        if not universe:
            continue
        market = _market_features_for_entry(as_of, market=None, data_store=data_store, universe=universe, cache=market_cache)
        returns_60d = _universe_returns_as_of(data_store, universe, as_of, 60)
        returns_252d = _universe_returns_as_of(data_store, universe, as_of, 252)
        univ_shares = universe_shares_as_of(pit_store, universe, as_of)  # cross-sectional float (S)
        if as_of not in taiex_cache:
            taiex_cache[as_of] = forward_returns_for(data_store, "TAIEX", as_of)
        if idx == 1 or idx % 12 == 0:
            logger.info("cohort %s/%s as_of=%s universe=%d rows=%d", idx, len(dates), as_of, len(universe), len(rows))
        for symbol in universe:
            fwd = forward_returns_for(data_store, symbol, as_of)
            if fwd is None:
                continue
            try:
                detail, fin_metrics, eps_filing = build_pit_inputs(symbol, as_of, pit_store)
                result = build_screening_result(
                    symbol, as_of, store=data_store, market=market,
                    fin_metrics=fin_metrics, detail=detail,
                    universe_returns_60d=returns_60d, universe_returns_252d=returns_252d,
                    event_window_active=False, eps_filing_date=eps_filing, n_pillar_analysis=None,
                    universe_shares=univ_shares,
                )
                full = build_full_result(result, params=params)
            except Exception as exc:  # never let one symbol abort the run
                logger.debug("screen failed %s @ %s: %s", symbol, as_of, exc)
                continue
            row: dict[str, Any] = {
                "as_of_date": as_of,
                "stock_id": symbol,
                "overall_score": full.overall_score,
                "score_band": _score_band(full.overall_score),
                "pass_status": full.pass_status,
                "grade": full.grade,
                "regime": result.market_regime,
                "confidence": full.confidence,
            }
            statuses = {f.factor: f.status for f in full.per_factor_scores}
            for pillar in PILLARS:
                row[f"{pillar}_status"] = statuses.get(pillar)
            row.update(fwd)
            rows.append(row)
    return pd.DataFrame(rows)


def _score_band(score: int | None) -> str:
    """Map overall_score to the same S/A/B/C/D bands the live ranking uses, so the
    cohort validates THE GRADING the user trades on (does a higher band grow more?)."""
    if score is None:
        return "NA"
    s = float(score)
    return "S(>=80)" if s >= 80 else "A(70-79)" if s >= 70 else "B(55-69)" if s >= 55 else "C(40-54)" if s >= 40 else "D(<40)"


def _bucket_metrics(frame: pd.DataFrame, col: str) -> dict[str, Any]:
    series = pd.to_numeric(frame[col], errors="coerce").dropna() if col in frame else pd.Series(dtype=float)
    if series.empty:
        return {"n": 0, "mean": None, "median": None, "pct_pos": None, "pct_gt20": None, "pct_gt50": None}
    return {
        "n": int(len(series)),
        "mean": round(float(series.mean()), 4),
        "median": round(float(series.median()), 4),
        "pct_pos": round(float((series > 0).mean()), 3),
        "pct_gt20": round(float((series >= 0.20).mean()), 3),
        "pct_gt50": round(float((series >= 0.50).mean()), 3),
    }


def summarize_cohort(df: pd.DataFrame) -> dict[str, Any]:
    horizons = [f"fwd_{name}" for name in HORIZONS]
    summary: dict[str, Any] = {
        "n_rows": int(len(df)),
        "by_pass_status": {},
        "baseline_all_screened": {},
        "by_pillar": {},
        "by_grade": {},
        "by_score_band": {},
    }
    if df.empty:
        return summary
    for h in horizons:
        summary["baseline_all_screened"][h] = _bucket_metrics(df, h)
    # THE key validation: does a higher CANSLIM score-band actually grow more?
    if "score_band" in df:
        band_order = ["S(>=80)", "A(70-79)", "B(55-69)", "C(40-54)", "D(<40)", "NA"]
        for band in [b for b in band_order if b in set(df["score_band"].dropna())]:
            sub = df[df["score_band"] == band]
            summary["by_score_band"][band] = {h: _bucket_metrics(sub, h) for h in horizons}
    for status in sorted(df["pass_status"].dropna().unique()):
        sub = df[df["pass_status"] == status]
        summary["by_pass_status"][status] = {h: _bucket_metrics(sub, h) for h in horizons}
    for grade in sorted(df["grade"].dropna().unique()):
        sub = df[df["grade"] == grade]
        summary["by_grade"][grade] = {h: _bucket_metrics(sub, h) for h in horizons}
    # Per-pillar: does this pillar's Pass predict better forward growth than non-Pass?
    for pillar in PILLARS:
        col = f"{pillar}_status"
        if col not in df:
            continue
        passed = df[df[col] == "Pass"]
        non_passed = df[df[col] != "Pass"]
        summary["by_pillar"][pillar] = {
            h: {"pass": _bucket_metrics(passed, h), "non_pass": _bucket_metrics(non_passed, h)}
            for h in horizons
        }
    return summary


def _fmt_metrics(m: dict[str, Any]) -> str:
    if not m or not m.get("n"):
        return "n=0"
    return f"n={m['n']} mean={m['mean']:+.2%} med={m['median']:+.2%} pos={m['pct_pos']:.0%} >20%={m['pct_gt20']:.0%} >50%={m['pct_gt50']:.0%}"


def _write_cohort_report(report: CohortReport, json_path: Path, md_path: Path) -> None:
    json_path.write_text(json.dumps(asdict(report), ensure_ascii=False, indent=2), encoding="utf-8")
    s = report.summary
    lines = [
        f"# CANSLIM screening cohort backtest: {report.run_id}",
        "",
        f"Period {report.start_date}..{report.end_date} | cadence {report.cadence_days}d | "
        f"{report.candidate_symbols} candidates | {report.n_rows} screened rows over {report.n_dates} dates | "
        f"{report.elapsed_seconds:.0f}s",
        "",
        "Forward-return cohorts. Compare each pass_status against `baseline_all_screened` "
        "(the average screened stock). Edge = PASS beats baseline beats WATCHLIST.",
        "",
        "## Forward return by pass_status",
    ]
    horizons = [f"fwd_{name}" for name in HORIZONS]
    lines.append("### ALL (baseline)")
    for h in horizons:
        lines.append(f"- {h}: {_fmt_metrics(s['baseline_all_screened'][h])}")
    # KEY: does a higher CANSLIM grade band actually grow more? (validates the grading)
    lines += ["", "## Forward return by CANSLIM score band (THE grading validation: higher band should grow more)"]
    for band, per_h in s.get("by_score_band", {}).items():
        lines.append(f"### {band}")
        for h in horizons:
            lines.append(f"- {h}: {_fmt_metrics(per_h[h])}")
    lines += ["", "## Forward return by pass_status"]
    for status, per_h in s.get("by_pass_status", {}).items():
        lines.append(f"### {status}")
        for h in horizons:
            lines.append(f"- {h}: {_fmt_metrics(per_h[h])}")
    lines += ["", "## Per-pillar Pass vs non-Pass (does each pillar predict forward growth?)"]
    for pillar, per_h in s.get("by_pillar", {}).items():
        lines.append(f"### {pillar}")
        for h in horizons:
            lines.append(f"- {h}: PASS {_fmt_metrics(per_h[h]['pass'])} | non-PASS {_fmt_metrics(per_h[h]['non_pass'])}")
    md_path.write_text("\n".join(lines), encoding="utf-8")


def run_cohort_backtest(
    *,
    run_id: str = "canslim_cohort_v1",
    ohlcv_db_path: Path | str = DEFAULT_DB_PATH,
    pit_db_path: Path | str = DEFAULT_PIT_DB_PATH,
    start_date: str = "2011-01-01",
    end_date: str = "2025-12-31",
    cadence_days: int = 21,
    output_dir: Path | str = "artifacts/canslim_cohort",
    candidate_symbols: list[str] | None = None,
    turnover_floor: float | None = None,
    max_staleness_days: int | None = None,
) -> CohortReport:
    started = time.time()
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows_csv = out_dir / "cohort_rows.csv"
    json_path = out_dir / "cohort_summary.json"
    md_path = out_dir / "cohort_summary.md"

    candidates = candidate_symbols or fundamentals_covered_symbols(pit_db_path)
    logger.info("cohort run %s: %d candidate symbols", run_id, len(candidates))
    data_store = CachedHistoricalDataStore(
        # TPEX required for regime (M-2); without it regime=unknown -> confidence LOW -> no PASS.
        ohlcv_db_path, universe=[*candidates, "TAIEX", "TPEX"],
        start_date=start_date, end_date=end_date,
        lookback_buffer_days=500, forward_buffer_days=420,
    )
    pit_store = CachedPitFundamentalsStore(pit_db_path, universe=candidates)
    params = load_params()
    dates = cadence_grid(data_store, start_date, end_date, cadence_days=cadence_days)
    df = _cohort_rows(
        data_store, pit_store, params, candidates, dates,
        turnover_floor=turnover_floor, max_staleness_days=max_staleness_days,
    )

    df.to_csv(rows_csv, index=False, encoding="utf-8-sig")
    report = CohortReport(
        run_id=run_id, start_date=start_date, end_date=end_date, cadence_days=cadence_days,
        candidate_symbols=len(candidates), n_rows=int(len(df)),
        n_dates=int(df["as_of_date"].nunique()) if not df.empty else 0,
        summary=summarize_cohort(df),
        rows_csv=str(rows_csv), summary_json=str(json_path), summary_md=str(md_path),
        elapsed_seconds=round(time.time() - started, 1),
    )
    _write_cohort_report(report, json_path, md_path)
    logger.info("cohort run done: %d rows, %s", report.n_rows, md_path)
    return report
