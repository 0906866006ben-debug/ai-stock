"""Quarterly TW-CANSLIM growth-screen portfolio backtest (MEASUREMENT ONLY).

Answers the user's real question: a CANSLIM growth screen, rebalanced every quarter,
that catches stocks which subsequently grow — and whether the online "video" version
(smallest-float selector) beats our survivorship-validated N/I-led version.

Two arms share the SAME eligibility filter (the video's C∩A∩G growth screen):
  - C: quarterly EPS YoY Pass (>= YAML threshold, default 25%)
  - A: 3y EPS CAGR Pass (>= threshold, default 25%)
  - G: latest monthly-revenue YoY >= min_revenue_yoy (default 10%), PIT-lagged to its
       ~10th-of-next-month disclosure (FinMind dates month revenue at the 1st of the next
       month; we add `revenue_publish_lag_days` so no rebalance sees not-yet-public revenue)
Then each arm picks its basket from the eligible set:
  - arm "video": the `basket_size` smallest free-float (CapitalStock/par) names
  - arm "ni":    the top `basket_size` by re-calibrated CANSLIM overall_score (N/I-led)

Equal weight, quarterly rebalance on a PIT-safe filing+revenue grid, round-trip cost +
slippage, limit-up no-fill (a name locked limit-up on the entry bar cannot be bought).
Reports annual returns / CAGR / maxDD / Calmar vs TAIEX. This is NOT a trading system and
emits no buy/sell/hold — it measures whether the screened baskets grow.

PIT discipline: screening reads only data <= as_of (rank_universe); forward bars are used
ONLY to measure the realized quarter return, never fed back into selection.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from backend.app.services.backtest.historical_data_store import CachedHistoricalDataStore, DEFAULT_DB_PATH
from backend.app.services.backtest.pit_fundamentals_store import CachedPitFundamentalsStore, DEFAULT_PIT_DB_PATH
from backend.app.services.strategy.canslim.canslim_ranking import rank_universe
from backend.app.services.strategy.canslim.pit_inputs import universe_shares_as_of

logger = logging.getLogger(__name__)

# PIT-safe quarterly grid: just after each TW report deadline AND after the monthly-revenue
# 10th-of-next-month disclosure, so no rebalance can see not-yet-public data.
#   ~4/15 (after FY annual 3/31), 5/16 (after Q1 5/15), 8/15 (after Q2 8/14), 11/15 (after Q3 11/14)
REBALANCE_GRID: tuple[tuple[int, int], ...] = ((4, 15), (5, 16), (8, 15), (11, 15))

# TW round-trip frictions: fee 0.1425% * 2 + securities tax 0.3% = 0.585%; plus slippage.
DEFAULT_ROUND_TRIP_COST = 0.00585
DEFAULT_SLIPPAGE = 0.002


@dataclass(frozen=True)
class QuarterlyConfig:
    arm: str = "ni"                          # "ni" (top score) | "video" (smallest float)
    basket_size: int = 30
    min_revenue_yoy: float = 0.10            # G filter
    revenue_publish_lag_days: int = 10       # month-revenue disclosure lag beyond stored date
    require_c_pass: bool = True              # C status must be Pass (EPS YoY >= threshold)
    require_a_pass: bool = True              # A status must be Pass (3y CAGR >= threshold)
    round_trip_cost: float = DEFAULT_ROUND_TRIP_COST
    slippage: float = DEFAULT_SLIPPAGE
    turnover_floor: float | None = None
    initial_capital: float = 1.0


@dataclass(frozen=True)
class QuarterlyResult:
    arm: str
    metrics: dict[str, Any]
    annual_returns: dict[str, float]
    equity_curve: pd.DataFrame
    rebalances: pd.DataFrame                 # per-rebalance: date, n_eligible, n_held, gross, net
    benchmark: dict[str, Any] = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────────────────
# Date grid
# ─────────────────────────────────────────────────────────────────────────────
def quarterly_rebalance_dates(store, start_date: str, end_date: str) -> list[str]:
    """First trading day on/after each grid date within [start, end]."""
    try:
        all_dates = store.get_all_trading_dates(start_date, end_date)
    except Exception:
        all_dates = None
    out: list[str] = []
    start_y = pd.Timestamp(start_date).year
    end_y = pd.Timestamp(end_date).year
    for year in range(start_y, end_y + 1):
        for mm, dd in REBALANCE_GRID:
            target = pd.Timestamp(year=year, month=mm, day=dd)
            if target < pd.Timestamp(start_date) or target > pd.Timestamp(end_date):
                continue
            trading = _first_trading_on_or_after(store, target.strftime("%Y-%m-%d"), all_dates)
            if trading and trading not in out:
                out.append(trading)
    return sorted(out)


def _first_trading_on_or_after(store, date_str: str, all_dates: list[str] | None) -> str | None:
    if all_dates:
        for d in all_dates:
            if d >= date_str:
                return d
        return None
    # Fallback: probe TAIEX bars around the target.
    bars = store.get_ohlcv_as_of("TAIEX", (pd.Timestamp(date_str) + pd.Timedelta(days=20)).strftime("%Y-%m-%d"), 40)
    if bars is None or bars.empty:
        return None
    future = [str(d)[:10] for d in bars["date"] if str(d)[:10] >= date_str]
    return future[0] if future else None


# ─────────────────────────────────────────────────────────────────────────────
# G filter (monthly-revenue YoY, PIT-lagged)
# ─────────────────────────────────────────────────────────────────────────────
def revenue_yoy_as_of(pit_store, symbol: str, as_of_date: str, lag_days: int) -> float | None:
    """Latest monthly-revenue YoY available (PUBLICLY) at as_of. Stored `date` is the 1st of
    the month AFTER the revenue month; we additionally require date + lag_days <= as_of so a
    not-yet-disclosed month (public only by ~the 10th) is never used. YoY is computed from
    the revenue series matched on (revenue_year, revenue_month) one year apart."""
    df = pit_store.get_month_revenue_as_of(symbol, as_of_date, limit=36)
    if df is None or df.empty:
        return None
    cutoff = (pd.Timestamp(as_of_date) - pd.Timedelta(days=int(lag_days)))
    rows = df[pd.to_datetime(df["date"], errors="coerce") <= cutoff]
    if rows.empty:
        return None
    by_ym: dict[tuple[int, int], float] = {}
    for _, r in rows.iterrows():
        try:
            raw = json.loads(r["raw_json"]) if r.get("raw_json") else {}
            y = int(raw.get("revenue_year")); m = int(raw.get("revenue_month"))
            rev = float(r["revenue"])
        except (TypeError, ValueError, KeyError):
            continue
        if rev > 0:
            by_ym[(y, m)] = rev
    if not by_ym:
        return None
    (ly, lm) = max(by_ym)
    cur = by_ym[(ly, lm)]
    prior = by_ym.get((ly - 1, lm))
    if prior is None or prior <= 0:
        return None
    return cur / prior - 1.0


# ─────────────────────────────────────────────────────────────────────────────
# Quarter return (equal-weight basket, costed, limit-up no-fill)
# ─────────────────────────────────────────────────────────────────────────────
def _entry_close(store, symbol: str, as_of_date: str) -> tuple[float | None, bool]:
    """(entry close, locked_limit_up) using the last bar on/before as_of."""
    bars = store.get_ohlcv_as_of(symbol, as_of_date, 5)
    if bars is None or len(bars) == 0:
        return None, False
    last = bars.iloc[-1]
    close = float(last["close"]) if pd.notna(last["close"]) else None
    locked = False
    if len(bars) >= 2 and close is not None:
        prev = float(bars.iloc[-2]["close"])
        hi = float(last["high"]) if pd.notna(last["high"]) else close
        if prev > 0 and (close / prev - 1.0) >= 0.095 and abs(close - hi) < 1e-9:
            locked = True
    return close, locked


def _exit_close(store, symbol: str, exit_date: str) -> float | None:
    bars = store.get_ohlcv_as_of(symbol, exit_date, 5)
    if bars is None or len(bars) == 0:
        return None
    val = bars.iloc[-1]["close"]
    return float(val) if pd.notna(val) else None


def basket_quarter_return(store, symbols: list[str], entry_date: str, exit_date: str, cfg: QuarterlyConfig) -> tuple[float, int]:
    """Equal-weight net return of the basket held entry->exit. Skips names locked limit-up at
    entry (no fill). Returns (net_return, n_filled)."""
    rets: list[float] = []
    for sym in symbols:
        ec, locked = _entry_close(store, sym, entry_date)
        if ec is None or ec <= 0 or locked:
            continue
        xc = _exit_close(store, sym, exit_date)
        if xc is None or xc <= 0:
            continue
        rets.append(xc / ec - 1.0)
    if not rets:
        return 0.0, 0
    gross = sum(rets) / len(rets)
    net = gross - (cfg.round_trip_cost + cfg.slippage)   # full quarterly turnover
    return net, len(rets)


# ─────────────────────────────────────────────────────────────────────────────
# Selection (the two arms over the shared C∩A∩G filter)
# ─────────────────────────────────────────────────────────────────────────────
def select_basket(ranked: pd.DataFrame, pit_store, as_of_date: str, cfg: QuarterlyConfig) -> list[str]:
    if ranked is None or ranked.empty:
        return []
    elig = ranked.copy()
    if cfg.require_c_pass:
        elig = elig[elig["C_status"] == "Pass"]
    if cfg.require_a_pass:
        elig = elig[elig["A_status"] == "Pass"]
    if elig.empty:
        return []
    # G filter: latest monthly-revenue YoY (PIT-lagged) >= min.
    g_ok: list[str] = []
    for sym in elig["stock_id"].tolist():
        yoy = revenue_yoy_as_of(pit_store, str(sym), as_of_date, cfg.revenue_publish_lag_days)
        if yoy is not None and yoy >= cfg.min_revenue_yoy:
            g_ok.append(str(sym))
    if not g_ok:
        return []
    if cfg.arm == "video":
        shares = universe_shares_as_of(pit_store, g_ok, as_of_date)
        with_float = [(s, shares.get(s)) for s in g_ok if shares.get(s)]
        with_float.sort(key=lambda t: float(t[1]))           # smallest free-float first
        return [s for s, _ in with_float[: cfg.basket_size]]
    # arm "ni": eligible set is already ordered by overall_score desc in `ranked`.
    ordered = [s for s in elig["stock_id"].astype(str).tolist() if s in set(g_ok)]
    return ordered[: cfg.basket_size]


# ─────────────────────────────────────────────────────────────────────────────
# Metrics
# ─────────────────────────────────────────────────────────────────────────────
def _metrics_from_curve(curve: pd.DataFrame, years: float) -> dict[str, Any]:
    if curve.empty or years <= 0:
        return {"cagr": 0.0, "max_drawdown": 0.0, "calmar": 0.0, "total_return": 0.0}
    eq = curve["equity"].astype(float)
    total = float(eq.iloc[-1] / eq.iloc[0] - 1.0)
    cagr = float((eq.iloc[-1] / eq.iloc[0]) ** (1.0 / years) - 1.0)
    peak = eq.cummax()
    max_dd = float((eq / peak - 1.0).min())
    calmar = float(cagr / abs(max_dd)) if max_dd < 0 else 0.0
    return {"cagr": round(cagr, 4), "max_drawdown": round(max_dd, 4),
            "calmar": round(calmar, 3), "total_return": round(total, 4)}


# ─────────────────────────────────────────────────────────────────────────────
# Driver
# ─────────────────────────────────────────────────────────────────────────────
def run_quarterly_backtest(
    *,
    run_id: str = "tw_canslim_q",
    ohlcv_db_path: Path | str = DEFAULT_DB_PATH,
    pit_db_path: Path | str = DEFAULT_PIT_DB_PATH,
    start_date: str = "2011-01-01",
    end_date: str = "2025-12-31",
    candidate_symbols: list[str] | None = None,
    arms: tuple[str, ...] = ("ni", "video"),
    basket_size: int = 30,
    min_revenue_yoy: float = 0.10,
    turnover_floor: float | None = 100_000_000,
    output_dir: Path | str = "artifacts/canslim_quarterly",
) -> dict[str, Any]:
    started = time.time()
    out_dir = Path(output_dir); out_dir.mkdir(parents=True, exist_ok=True)
    from backend.app.services.strategy.canslim.multicycle_backtest import fundamentals_covered_symbols
    candidates = candidate_symbols or fundamentals_covered_symbols(pit_db_path)
    logger.info("quarterly backtest %s: %d candidates", run_id, len(candidates))

    data_store = CachedHistoricalDataStore(
        ohlcv_db_path, universe=[*candidates, "TAIEX", "TPEX"],
        start_date=start_date, end_date=end_date,
        lookback_buffer_days=500, forward_buffer_days=130,
    )
    pit_store = CachedPitFundamentalsStore(pit_db_path, universe=candidates)
    dates = quarterly_rebalance_dates(data_store, start_date, end_date)
    logger.info("%d quarterly rebalance dates %s..%s", len(dates), dates[0] if dates else "-", dates[-1] if dates else "-")

    # Rank once per rebalance date (shared by both arms).
    ranked_by_date: dict[str, pd.DataFrame] = {}
    for i, d in enumerate(dates, 1):
        ranked_by_date[d] = rank_universe(d, data_store, pit_store, candidate_symbols=candidates, turnover_floor=turnover_floor)
        logger.info("ranked %d/%d at %s (%d scored)", i, len(dates), d, len(ranked_by_date[d]))

    results: dict[str, QuarterlyResult] = {}
    for arm in arms:
        cfg = QuarterlyConfig(arm=arm, basket_size=basket_size, min_revenue_yoy=min_revenue_yoy, turnover_floor=turnover_floor)
        results[arm] = _simulate_arm(data_store, pit_store, dates, ranked_by_date, cfg)

    bench = _benchmark(data_store, dates)
    report = _write_report(run_id, out_dir, results, bench, dates, started)
    return report


def _close_series(store, symbol: str, start: str, end: str, lookback: int = 180) -> pd.Series | None:
    """Daily close series (index = 'YYYY-MM-DD') for [start, end], or None."""
    bars = store.get_ohlcv_as_of(symbol, end, lookback)
    if bars is None or bars.empty:
        return None
    b = bars.copy()
    b["_d"] = b["date"].astype(str).str[:10]
    b = b[(b["_d"] >= start) & (b["_d"] <= end)]
    if b.empty:
        return None
    s = pd.Series(pd.to_numeric(b["close"], errors="coerce").values, index=b["_d"].values).dropna()
    return s if not s.empty else None


def _trading_days(store, entry: str, exit_: str) -> list[str]:
    """TAIEX trading days in (entry, exit] — the daily mark-to-market grid for a quarter."""
    s = _close_series(store, "TAIEX", entry, exit_)
    if s is None:
        return [exit_]
    days = [d for d in s.index if d > entry]
    return days or [exit_]


def _quarter_daily_equity(store, basket, entry, exit_, start_equity, cfg: QuarterlyConfig):
    """DAILY mark-to-market equity for the equal-weight basket held entry->exit, so maxDD
    captures intra-quarter troughs (quarterly-point sampling hides them). Round-trip cost +
    slippage applied once at entry as a haircut. Limit-up-locked / no-data names are skipped
    (no fill). Delisted-mid-quarter names carry at their last available close.
    Returns (list[{date, equity}] over (entry, exit], end_equity, n_filled)."""
    held: dict[str, float] = {}
    for sym in basket:
        ec, locked = _entry_close(store, sym, entry)
        if ec and ec > 0 and not locked:
            held[sym] = ec
    if not held:
        return [{"date": exit_, "equity": start_equity}], start_equity, 0
    base = start_equity * (1.0 - (cfg.round_trip_cost + cfg.slippage))
    series = {sym: _close_series(store, sym, entry, exit_) for sym in held}
    rows: list[dict[str, Any]] = []
    end_equity = base
    for d in _trading_days(store, entry, exit_):
        rets: list[float] = []
        for sym, ec in held.items():
            s = series.get(sym)
            if s is None:
                rets.append(1.0)
                continue
            sub = s[s.index <= d]
            c = float(sub.iloc[-1]) if len(sub) else ec     # carry last close (delisted) / entry
            rets.append(c / ec)
        factor = sum(rets) / len(rets)
        end_equity = base * factor
        rows.append({"date": d, "equity": end_equity})
    return rows, end_equity, len(held)


def _simulate_arm(data_store, pit_store, dates, ranked_by_date, cfg: QuarterlyConfig) -> QuarterlyResult:
    equity = float(cfg.initial_capital)
    curve_rows: list[dict[str, Any]] = [{"date": dates[0], "equity": equity}]
    rebal_rows: list[dict[str, Any]] = []
    for entry, exit_ in zip(dates[:-1], dates[1:]):
        basket = select_basket(ranked_by_date.get(entry), pit_store, entry, cfg)
        day_rows, end_equity, n_filled = _quarter_daily_equity(data_store, basket, entry, exit_, equity, cfg)
        curve_rows.extend(day_rows)
        net = end_equity / equity - 1.0 if equity else 0.0
        rebal_rows.append({"date": entry, "n_selected": len(basket), "n_held": n_filled, "net_return": round(net, 4)})
        equity = end_equity
    curve = pd.DataFrame(curve_rows).drop_duplicates(subset="date", keep="last").reset_index(drop=True)
    years = max((pd.Timestamp(dates[-1]) - pd.Timestamp(dates[0])).days / 365.25, 1e-9)
    return QuarterlyResult(
        arm=cfg.arm, metrics=_metrics_from_curve(curve, years), annual_returns=_annual_returns(curve),
        equity_curve=curve, rebalances=pd.DataFrame(rebal_rows),
    )


def _annual_returns(curve: pd.DataFrame) -> dict[str, float]:
    if curve.empty:
        return {}
    c = curve.copy()
    c["year"] = pd.to_datetime(c["date"]).dt.year
    out: dict[str, float] = {}
    for year, g in c.groupby("year"):
        eq = g["equity"].astype(float)
        out[str(int(year))] = round(float(eq.iloc[-1] / eq.iloc[0] - 1.0), 4)
    return out


def _benchmark(data_store, dates) -> dict[str, Any]:
    # Daily TAIEX so its maxDD is comparable to the daily-MTM strategy curve (quarterly-point
    # sampling understated it, e.g. the smoke's deceptive -1.8%).
    s = _close_series(data_store, "TAIEX", dates[0], dates[-1], lookback=6000)
    if s is None or s.empty:
        return {"metrics": _metrics_from_curve(pd.DataFrame(columns=["date", "equity"]), 1.0), "annual_returns": {}}
    base = float(s.iloc[0])
    curve = pd.DataFrame({"date": list(s.index), "equity": (s.values / base)})
    years = max((pd.Timestamp(dates[-1]) - pd.Timestamp(dates[0])).days / 365.25, 1e-9)
    return {"metrics": _metrics_from_curve(curve, years), "annual_returns": _annual_returns(curve)}


def _write_report(run_id, out_dir, results: dict[str, QuarterlyResult], bench, dates, started) -> dict[str, Any]:
    report: dict[str, Any] = {
        "run_id": run_id, "start": dates[0], "end": dates[-1], "n_rebalances": len(dates) - 1,
        "elapsed_seconds": round(time.time() - started, 1),
        "benchmark_TAIEX": bench, "arms": {},
    }
    for arm, res in results.items():
        report["arms"][arm] = {"metrics": res.metrics, "annual_returns": res.annual_returns}
        res.equity_curve.to_csv(out_dir / f"equity_{arm}.csv", index=False, encoding="utf-8-sig")
        res.rebalances.to_csv(out_dir / f"rebalances_{arm}.csv", index=False, encoding="utf-8-sig")
    (out_dir / "quarterly_summary.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "quarterly_summary.md").write_text(_markdown(report), encoding="utf-8")
    return report


def _markdown(report: dict[str, Any]) -> str:
    b = report["benchmark_TAIEX"]["metrics"]
    lines = [
        f"# TW-CANSLIM quarterly backtest: {report['run_id']}",
        f"\n{report['start']}..{report['end']} | {report['n_rebalances']} rebalances | {report['elapsed_seconds']}s\n",
        "## Headline (net of cost+slippage, survivorship-corrected if delisted in universe)\n",
        "| Arm | CAGR | maxDD | Calmar | TotalRet |",
        "|---|---|---|---|---|",
        f"| TAIEX (benchmark) | {b['cagr']:+.1%} | {b['max_drawdown']:+.1%} | {b['calmar']:.2f} | {b['total_return']:+.1%} |",
    ]
    for arm, a in report["arms"].items():
        m = a["metrics"]
        label = "ni (N/I-led, ours)" if arm == "ni" else "video (smallest-float)" if arm == "video" else arm
        lines.append(f"| {label} | {m['cagr']:+.1%} | {m['max_drawdown']:+.1%} | {m['calmar']:.2f} | {m['total_return']:+.1%} |")
    lines.append("\n## Annual returns\n")
    years = sorted(report["benchmark_TAIEX"]["annual_returns"].keys())
    header = "| Year | TAIEX | " + " | ".join(report["arms"].keys()) + " |"
    lines.append(header); lines.append("|" + "---|" * (len(report["arms"]) + 2))
    for y in years:
        row = [y, f"{report['benchmark_TAIEX']['annual_returns'].get(y, 0):+.1%}"]
        for arm in report["arms"]:
            row.append(f"{report['arms'][arm]['annual_returns'].get(y, 0):+.1%}")
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines) + "\n"
