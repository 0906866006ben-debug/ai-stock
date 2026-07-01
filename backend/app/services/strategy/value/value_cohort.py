"""Value-factor forward-return cohort backtest (measurement only, Phase 1).

Empirically tests whether the value/quality factors built in Phase 0 carry a real
forward-return edge ON OUR OWN PIT-SAFE TAIWAN DATA — we do NOT trust external
marketing numbers (e.g. FinLab's claimed ~10% F-Score spread). The first factor under
the microscope is the Piotroski F-Score.

Method (annual rebalance, decile / score-bucket cohort):
- On each annual `as_of` date, build the PIT liquidity universe. Survivorship is
  corrected by merging already-delisted symbols (the CLI does this) and dropping a
  name once its last bar goes stale (``max_staleness_days``).
- For every symbol compute the factor (F-Score 0-9 / Magic-Formula combined rank /
  Shareholder Yield) from data filed <= as_of (PIT-safe via ``get_*_as_of``).
- Group cross-sectionally: F-Score by its integer value (0-9 = ten natural buckets);
  continuous factors by per-date decile (D1..D10).
- Measure each name's forward 1/3/6/12-month return, **net of 0.685% round-trip cost**,
  and the excess over TAIEX. 12m is the annual ("次年") holding return.

Decision gate the report surfaces: does the high bucket (F-Score >= 8) beat the low
bucket (<= 2) and beat TAIEX, consistently across years and within size tertiles?
Reproduce the ~10% spread or downgrade the factor for Taiwan.

This is measurement: fixed params, no tuning. Screening/factor code reads only data
<= as_of; forward bars measure outcomes only, never feed back.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from backend.app.services.backtest.historical_data_store import (
    CachedHistoricalDataStore,
    DEFAULT_DB_PATH,
)
from backend.app.services.backtest.pit_fundamentals_store import (
    CachedPitFundamentalsStore,
    DEFAULT_PIT_DB_PATH,
)
from backend.app.services.strategy.canslim.cohort_backtest import HORIZONS, forward_returns_for
from backend.app.services.strategy.canslim.multicycle_backtest import cadence_grid
from backend.app.services.strategy.canslim.params import load_params
from backend.app.services.strategy.canslim.pit_inputs import _shares_outstanding
from backend.app.services.strategy.canslim.pit_universe import get_universe_as_of
from backend.app.services.strategy.value.value_factors import (
    magic_formula,
    piotroski_fscore,
    shareholder_yield,
)

logger = logging.getLogger(__name__)

# Round-trip transaction cost deducted from every forward return (TW: 0.1425%*2 fee
# discounted + 0.3% sell tax ≈ 0.685%). Applied as a flat haircut on gross return.
COST_ROUNDTRIP = 0.00685
FACTORS = ("fscore", "magic", "sy")
DECILES = [f"D{i}" for i in range(1, 11)]


@dataclass
class ValueCohortReport:
    run_id: str
    factor: str
    start_date: str
    end_date: str
    cadence_days: int
    candidate_symbols: int
    cost_roundtrip: float
    n_rows: int
    n_dates: int
    summary: dict[str, Any]
    rows_csv: str
    summary_json: str
    summary_md: str
    elapsed_seconds: float = 0.0


# ── factor computation ──────────────────────────────────────────────────────
def _market_cap(data_store, pit_store, symbol: str, as_of: str) -> float | None:
    """Approx market cap = latest close (<= as_of) x shares (CapitalStock/10). PIT-safe."""
    bars = data_store.get_ohlcv_as_of(symbol, as_of, 1)
    if bars is None or bars.empty:
        return None
    close = float(bars["close"].iloc[-1])
    bs = pit_store.get_balance_sheet_as_of(symbol, as_of, limit=1)
    shares = _shares_outstanding(bs)
    if shares is None or close <= 0:
        return None
    return close * shares


def _factor_for_symbol(
    data_store, pit_store, params, symbol: str, as_of: str, factor: str
) -> dict[str, Any] | None:
    """Compute the requested factor for one symbol at as_of. Returns a row dict with the
    factor value(s) + market cap, or None when the factor cannot be computed (no fabrication)."""
    fin = pit_store.get_financials_as_of(symbol, as_of, limit=12)
    bs = pit_store.get_balance_sheet_as_of(symbol, as_of, limit=8)
    mc = _market_cap(data_store, pit_store, symbol, as_of)
    out: dict[str, Any] = {"market_cap": mc}
    if factor == "fscore":
        cf = pit_store.get_cash_flow_as_of(symbol, as_of, limit=8)
        score = piotroski_fscore(financials=fin, balance_sheet=bs, cash_flow=cf, params=params)
        if score is None:
            return None
        out["factor_value"] = float(score)
        out["fscore"] = int(score)
        return out
    if factor == "magic":
        mf = magic_formula(financials=fin, balance_sheet=bs, market_cap=mc, params=params)
        if mf["ey"] is None or mf["roc"] is None:
            return None
        out["ey"] = mf["ey"]
        out["roc"] = mf["roc"]
        out["factor_value"] = None   # filled by cross-sectional combined rank in _assign_groups
        return out
    if factor == "sy":
        per = pit_store.get_per_as_of(symbol, as_of, limit=60)
        sy = shareholder_yield(balance_sheet=bs, per=per, market_cap=mc, params=params)
        if sy["total"] is None:
            return None
        out["factor_value"] = float(sy["total"])
        return out
    raise ValueError(f"unknown factor: {factor}")


# ── cohort rows ───────────────────────────────────────────────────────────────
def _value_cohort_rows(
    data_store,
    pit_store,
    params,
    candidates: list[str],
    dates: list[str],
    factor: str,
    *,
    turnover_floor: float | None = None,
    max_staleness_days: int | None = None,
) -> pd.DataFrame:
    """Build one row per (as_of, symbol): factor value + market cap + net forward returns
    + TAIEX forward returns. Pure over the injected stores (unit-testable)."""
    taiex_cache: dict[str, dict[str, Any] | None] = {}
    rows: list[dict[str, Any]] = []
    for idx, as_of in enumerate(dates, start=1):
        universe = get_universe_as_of(
            as_of, data_store, turnover_floor=turnover_floor,
            candidate_symbols=candidates, max_staleness_days=max_staleness_days,
        )
        if not universe:
            continue
        if as_of not in taiex_cache:
            taiex_cache[as_of] = forward_returns_for(data_store, "TAIEX", as_of)
        taiex_fwd = taiex_cache[as_of] or {}
        logger.info("value cohort %s/%s as_of=%s universe=%d rows=%d", idx, len(dates), as_of, len(universe), len(rows))
        for symbol in universe:
            fwd = forward_returns_for(data_store, symbol, as_of)
            if fwd is None:
                continue
            try:
                fv = _factor_for_symbol(data_store, pit_store, params, symbol, as_of, factor)
            except Exception as exc:  # never let one symbol abort the run
                logger.debug("factor failed %s @ %s: %s", symbol, as_of, exc)
                continue
            if fv is None:
                continue
            row: dict[str, Any] = {"as_of_date": as_of, "year": as_of[:4], "stock_id": symbol}
            row.update(fv)
            # Net forward return = gross - round-trip cost; excess = net - TAIEX (gross index).
            for name in HORIZONS:
                gross = fwd.get(f"fwd_{name}")
                row[f"gross_{name}"] = gross
                row[f"net_{name}"] = round(gross - COST_ROUNDTRIP, 6) if gross is not None else None
                tx = taiex_fwd.get(f"fwd_{name}")
                row[f"taiex_{name}"] = tx
                if gross is not None and tx is not None:
                    row[f"excess_{name}"] = round((gross - COST_ROUNDTRIP) - tx, 6)
                else:
                    row[f"excess_{name}"] = None
            rows.append(row)
    df = pd.DataFrame(rows)
    if not df.empty:
        df = _assign_groups(df, factor)
    return df


def _assign_groups(df: pd.DataFrame, factor: str) -> pd.DataFrame:
    """Add a cross-sectional `group` column. F-Score buckets by integer value (0-9);
    continuous factors by per-date decile (D1=lowest .. D10=highest factor)."""
    if factor == "fscore":
        df["group"] = df["fscore"].apply(lambda s: f"F{int(s)}" if pd.notna(s) else None)
        return df
    # Magic Formula: combined Greenblatt rank (higher EY + higher ROC = better) per date.
    if factor == "magic":
        def _combined(g: pd.DataFrame) -> pd.Series:
            ey_rank = g["ey"].rank(method="first")
            roc_rank = g["roc"].rank(method="first")
            return ey_rank + roc_rank   # higher = cheaper + higher-return-on-capital
        df["factor_value"] = df.groupby("as_of_date", group_keys=False).apply(_combined)
    # Decile per as_of on factor_value (D10 = highest factor value).
    df["group"] = df.groupby("as_of_date", group_keys=False)["factor_value"].apply(_decile_labels)
    return df


def _decile_labels(series: pd.Series) -> pd.Series:
    vals = pd.to_numeric(series, errors="coerce")
    valid = vals.dropna()
    if len(valid) < 10:
        return pd.Series([None] * len(series), index=series.index)
    ranks = valid.rank(method="first")
    codes = pd.qcut(ranks, 10, labels=False, duplicates="drop")
    labels = codes.apply(lambda c: f"D{int(c) + 1}" if pd.notna(c) else None)
    return labels.reindex(series.index)


# ── summary ───────────────────────────────────────────────────────────────────
def _bucket(frame: pd.DataFrame, col: str) -> dict[str, Any]:
    series = pd.to_numeric(frame[col], errors="coerce").dropna() if col in frame else pd.Series(dtype=float)
    if series.empty:
        return {"n": 0, "mean": None, "median": None, "pct_pos": None}
    return {
        "n": int(len(series)),
        "mean": round(float(series.mean()), 4),
        "median": round(float(series.median()), 4),
        "pct_pos": round(float((series > 0).mean()), 3),
    }


def summarize_value_cohort(df: pd.DataFrame, factor: str, params: Any) -> dict[str, Any]:
    horizons = list(HORIZONS)
    summary: dict[str, Any] = {
        "factor": factor,
        "n_rows": int(len(df)),
        "by_group_net": {},
        "by_group_excess": {},
        "high_minus_low": {},
        "by_year_high_minus_low": {},
        "size_control": {},
        "baseline": {},
    }
    if df.empty:
        return summary

    for h in horizons:
        summary["baseline"][h] = _bucket(df, f"net_{h}")

    groups = _ordered_groups(df, factor)
    for g in groups:
        sub = df[df["group"] == g]
        summary["by_group_net"][g] = {h: _bucket(sub, f"net_{h}") for h in horizons}
        summary["by_group_excess"][g] = {h: _bucket(sub, f"excess_{h}") for h in horizons}

    high_mask, low_mask, hl_label = _high_low_masks(df, factor, params)
    high, low = df[high_mask], df[low_mask]
    summary["high_low_label"] = hl_label
    for h in horizons:
        hb, lb = _bucket(high, f"net_{h}"), _bucket(low, f"net_{h}")
        spread = (hb["mean"] - lb["mean"]) if (hb["mean"] is not None and lb["mean"] is not None) else None
        summary["high_minus_low"][h] = {
            "high": hb, "low": lb,
            "spread_net": round(spread, 4) if spread is not None else None,
            "high_excess_vs_taiex": _bucket(high, f"excess_{h}")["mean"],
        }

    # Yearly consistency on the annual (12m) horizon: high-low spread per year.
    for year in sorted(df["year"].dropna().unique()):
        ysub = df[df["year"] == year]
        yhigh = ysub[_high_low_masks(ysub, factor, params)[0]]
        ylow = ysub[_high_low_masks(ysub, factor, params)[1]]
        hb, lb = _bucket(yhigh, "net_12m"), _bucket(ylow, "net_12m")
        spread = (hb["mean"] - lb["mean"]) if (hb["mean"] is not None and lb["mean"] is not None) else None
        summary["by_year_high_minus_low"][str(year)] = {
            "high_n": hb["n"], "high_mean": hb["mean"], "low_n": lb["n"], "low_mean": lb["mean"],
            "spread_net_12m": round(spread, 4) if spread is not None else None,
        }

    # Size control: is the edge just small caps? Recompute 12m high-low within market-cap tertiles.
    if df["market_cap"].notna().any():
        df = df.copy()
        df["size_tertile"] = df.groupby("as_of_date", group_keys=False)["market_cap"].apply(_tertile_labels)
        for tier in ("small", "mid", "large"):
            tsub = df[df["size_tertile"] == tier]
            thigh = tsub[_high_low_masks(tsub, factor, params)[0]]
            tlow = tsub[_high_low_masks(tsub, factor, params)[1]]
            hb, lb = _bucket(thigh, "net_12m"), _bucket(tlow, "net_12m")
            spread = (hb["mean"] - lb["mean"]) if (hb["mean"] is not None and lb["mean"] is not None) else None
            summary["size_control"][tier] = {
                "high_n": hb["n"], "high_mean": hb["mean"], "low_n": lb["n"], "low_mean": lb["mean"],
                "spread_net_12m": round(spread, 4) if spread is not None else None,
            }
    return summary


def _ordered_groups(df: pd.DataFrame, factor: str) -> list[str]:
    present = set(df["group"].dropna().unique())
    if factor == "fscore":
        return [f"F{i}" for i in range(0, 10) if f"F{i}" in present]
    return [d for d in DECILES if d in present]


def _high_low_masks(df: pd.DataFrame, factor: str, params: Any):
    """(high_mask, low_mask, label). F-Score uses YAML quality bands; deciles use D10 vs D1."""
    if factor == "fscore":
        cfg = params.get("value", {}) if hasattr(params, "get") else {}
        hi = int(cfg.get("fscore_high_quality_min", 8))
        lo = int(cfg.get("fscore_low_quality_max", 2))
        fs = pd.to_numeric(df.get("fscore"), errors="coerce")
        return (fs >= hi), (fs <= lo), f"high(F>={hi}) vs low(F<={lo})"
    return (df["group"] == "D10"), (df["group"] == "D1"), "high(D10) vs low(D1)"


def _tertile_labels(series: pd.Series) -> pd.Series:
    vals = pd.to_numeric(series, errors="coerce")
    valid = vals.dropna()
    if len(valid) < 3:
        return pd.Series([None] * len(series), index=series.index)
    ranks = valid.rank(method="first")
    codes = pd.qcut(ranks, 3, labels=["small", "mid", "large"], duplicates="drop")
    return codes.reindex(series.index)


# ── report ────────────────────────────────────────────────────────────────────
def _fmt(m: dict[str, Any]) -> str:
    if not m or not m.get("n"):
        return "n=0"
    return f"n={m['n']} mean={m['mean']:+.2%} med={m['median']:+.2%} pos={m['pct_pos']:.0%}"


def _write_value_report(report: ValueCohortReport, json_path: Path, md_path: Path) -> None:
    json_path.write_text(json.dumps(asdict(report), ensure_ascii=False, indent=2), encoding="utf-8")
    s = report.summary
    horizons = list(HORIZONS)
    lines = [
        f"# Value-factor cohort backtest: {report.run_id} (factor={report.factor})",
        "",
        f"Period {report.start_date}..{report.end_date} | annual cadence {report.cadence_days}d | "
        f"{report.candidate_symbols} candidates (incl. delisted if merged) | "
        f"{report.n_rows} rows over {report.n_dates} dates | round-trip cost {report.cost_roundtrip:.3%} | "
        f"{report.elapsed_seconds:.0f}s",
        "",
        "All returns are NET of round-trip cost. `excess` = net return − TAIEX over the same window. "
        "12m = the annual (次年) holding return.",
        "",
        "## DECISION GATE — high vs low bucket (does the factor carry an edge?)",
        f"High/low definition: **{s.get('high_low_label', 'n/a')}**",
    ]
    for h in horizons:
        hl = s["high_minus_low"].get(h, {})
        spread = hl.get("spread_net")
        spread_str = f"{spread:+.2%}" if spread is not None else "n/a"
        lines.append(
            f"- {h}: HIGH {_fmt(hl.get('high', {}))} | LOW {_fmt(hl.get('low', {}))} "
            f"→ **spread(net) {spread_str}** | high vs TAIEX "
            f"{(hl.get('high_excess_vs_taiex') or 0):+.2%}"
        )

    lines += ["", "## Forward NET return by bucket"]
    for g, per_h in s.get("by_group_net", {}).items():
        lines.append(f"### {g}")
        for h in horizons:
            lines.append(f"- {h}: {_fmt(per_h[h])} | excess vs TAIEX: "
                         f"{_fmt(s['by_group_excess'][g][h])}")

    lines += ["", "## Yearly consistency — high−low spread (net, 12m)"]
    for year, d in s.get("by_year_high_minus_low", {}).items():
        sp = d.get("spread_net_12m")
        lines.append(f"- {year}: high n={d['high_n']} mean="
                     f"{(d['high_mean'] or 0):+.2%} | low n={d['low_n']} mean={(d['low_mean'] or 0):+.2%} "
                     f"→ spread {f'{sp:+.2%}' if sp is not None else 'n/a'}")

    lines += ["", "## Size control — high−low spread (net, 12m) within market-cap tertiles",
              "(Confirms the edge is not purely a small-cap artefact.)"]
    for tier, d in s.get("size_control", {}).items():
        sp = d.get("spread_net_12m")
        lines.append(f"- {tier}: high n={d['high_n']} mean={(d['high_mean'] or 0):+.2%} | "
                     f"low n={d['low_n']} mean={(d['low_mean'] or 0):+.2%} "
                     f"→ spread {f'{sp:+.2%}' if sp is not None else 'n/a'}")
    lines += ["", "## Baseline (all names, net)"]
    for h in horizons:
        lines.append(f"- {h}: {_fmt(s['baseline'][h])}")
    lines += ["", "_Industry control not applied (needs a PIT sector map); size control above "
              "addresses the primary confound. Validate before deployment._"]
    md_path.write_text("\n".join(lines), encoding="utf-8")


def run_value_cohort(
    *,
    factor: str = "fscore",
    run_id: str | None = None,
    ohlcv_db_path: Path | str = DEFAULT_DB_PATH,
    pit_db_path: Path | str = DEFAULT_PIT_DB_PATH,
    start_date: str = "2011-01-01",
    end_date: str = "2025-12-31",
    cadence_days: int = 252,
    output_dir: Path | str = "artifacts/value_cohort",
    candidate_symbols: list[str],
    turnover_floor: float | None = None,
    max_staleness_days: int | None = None,
) -> ValueCohortReport:
    if factor not in FACTORS:
        raise ValueError(f"factor must be one of {FACTORS}, got {factor!r}")
    started = time.time()
    run_id = run_id or f"value_cohort_{factor}"
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows_csv = out_dir / f"value_cohort_{factor}_rows.csv"
    json_path = out_dir / f"value_cohort_{factor}_summary.json"
    md_path = out_dir / f"value_cohort_{factor}_summary.md"

    candidates = list(candidate_symbols)
    logger.info("value cohort %s: factor=%s, %d candidate symbols", run_id, factor, len(candidates))
    data_store = CachedHistoricalDataStore(
        ohlcv_db_path, universe=[*candidates, "TAIEX"],
        start_date=start_date, end_date=end_date,
        lookback_buffer_days=500, forward_buffer_days=420,
    )
    pit_store = CachedPitFundamentalsStore(pit_db_path, universe=candidates)
    params = load_params()
    dates = cadence_grid(data_store, start_date, end_date, cadence_days=cadence_days)
    logger.info("annual cadence -> %d rebalance dates", len(dates))
    df = _value_cohort_rows(
        data_store, pit_store, params, candidates, dates, factor,
        turnover_floor=turnover_floor, max_staleness_days=max_staleness_days,
    )

    df.to_csv(rows_csv, index=False, encoding="utf-8-sig")
    report = ValueCohortReport(
        run_id=run_id, factor=factor, start_date=start_date, end_date=end_date,
        cadence_days=cadence_days, candidate_symbols=len(candidates),
        cost_roundtrip=COST_ROUNDTRIP, n_rows=int(len(df)),
        n_dates=int(df["as_of_date"].nunique()) if not df.empty else 0,
        summary=summarize_value_cohort(df, factor, params),
        rows_csv=str(rows_csv), summary_json=str(json_path), summary_md=str(md_path),
        elapsed_seconds=round(time.time() - started, 1),
    )
    _write_value_report(report, json_path, md_path)
    logger.info("value cohort done: %d rows, %s", report.n_rows, md_path)
    return report
