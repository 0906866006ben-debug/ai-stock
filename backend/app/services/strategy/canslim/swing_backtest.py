"""Swing backtest — measure the strategy you ACTUALLY trade, nothing else.

Anti-"white work" design (Wall-Street-quant rationale):
  * ENTRY = the live screen's actionable output: `pass_status == PASS` from
    `build_full_result` (NOT the grade letter, which we proved is OOS-unstable, so
    entering/optimizing on it measures noise).
  * EXIT  = aligned to the live `swing_exit`: a hard catastrophe stop, a trend-break
    exit (daily close below the swing MA — the live "weakening"/structure line), a
    swing profit target, and a max-hold cap. Whichever fires first.
  * Fixed params, continuous 2011→2025, PIT-safe, costs in, reported BY REGIME
    (bear-year drawdown is the known killer, per prior validation). No tuning, no
    window re-slicing (that overfits 2022).

This does NOT change any signal/score/grade math, and it does NOT touch the validated
multicycle/trade_simulator path (it has its own self-contained exit walk). It reuses the
cohort screening machinery for entries.
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


@dataclass
class SwingRules:
    entry_pass_status: str = "PASS"
    stop_pct: float = 0.08
    target_pct: float = 0.25
    exit_ma_days: int = 20
    max_hold_days: int = 60
    round_trip_cost_pct: float = 0.00685
    slippage_pct: float = 0.001

    @classmethod
    def from_params(cls, params) -> "SwingRules":
        bt = params.get("backtest", {})
        sw = bt.get("swing", {})
        costs = bt.get("costs", {})
        return cls(
            entry_pass_status=str(sw.get("entry_pass_status", "PASS")),
            stop_pct=float(sw.get("stop_pct", 0.08)),
            target_pct=float(sw.get("target_pct", 0.25)),
            exit_ma_days=int(sw.get("exit_ma_days", 20)),
            max_hold_days=int(sw.get("max_hold_days", 60)),
            round_trip_cost_pct=float(costs.get("round_trip_cost_pct", 0.00685)),
        )


@dataclass
class SwingReport:
    run_id: str
    start_date: str
    end_date: str
    cadence_days: int
    candidate_symbols: int
    n_trades: int
    rules: dict[str, Any]
    overall: dict[str, Any]
    by_regime: dict[str, Any]
    trades_csv: str
    summary_json: str
    summary_md: str
    elapsed_seconds: float = 0.0


def simulate_swing_trade(store, stock_id: str, as_of_date: str, rules: SwingRules) -> dict[str, Any] | None:
    """Enter at the first tradable OPEN after as_of; exit on the first of: hard stop,
    daily close < MA(exit_ma_days), profit target, max-hold. Returns trade dict or None
    (no tradable forward data). PIT-safe: only bars on/after entry are used for exit."""
    # Window: enough pre-history to seed the exit MA + forward room for the hold.
    end = (pd.Timestamp(as_of_date) + pd.Timedelta(days=int(rules.max_hold_days * 2.0) + 30)).strftime("%Y-%m-%d")
    start = (pd.Timestamp(as_of_date) - pd.Timedelta(days=int(rules.exit_ma_days * 2) + 20)).strftime("%Y-%m-%d")
    bars = store.get_ohlcv(stock_id, start, end)
    if bars is None or bars.empty:
        return None
    bars = bars.reset_index(drop=True)
    bars["ma"] = pd.to_numeric(bars["close"], errors="coerce").rolling(rules.exit_ma_days).mean()
    fwd = bars[bars["date"] > as_of_date].reset_index(drop=True)
    fwd = fwd[pd.to_numeric(fwd["open"], errors="coerce") > 0].reset_index(drop=True)
    if fwd.empty:
        return None

    entry = fwd.iloc[0]
    entry_price = float(entry["open"]) * (1 + rules.slippage_pct)
    if entry_price <= 0:
        return None
    stop_price = entry_price * (1 - rules.stop_pct)
    target_price = entry_price * (1 + rules.target_pct)

    exit_price = exit_reason = None
    hold_days = 0
    for pos in range(1, len(fwd)):  # exit evaluated from the bar AFTER entry
        bar = fwd.iloc[pos]
        hold_days = pos
        low, high, close, ma = float(bar["low"]), float(bar["high"]), float(bar["close"]), bar["ma"]
        if low <= stop_price:
            exit_price, exit_reason = stop_price, "stop_loss"; break
        if high >= target_price:
            exit_price, exit_reason = target_price, "target"; break
        if pd.notna(ma) and close < float(ma):
            exit_price, exit_reason = close, "ma_break"; break
        if hold_days >= rules.max_hold_days:
            exit_price, exit_reason = close, "max_hold"; break
    if exit_price is None:  # ran out of forward data
        last = fwd.iloc[-1]
        exit_price, exit_reason, hold_days = float(last["close"]), "no_exit_data", len(fwd) - 1

    exit_price *= (1 - rules.slippage_pct)
    gross = exit_price / entry_price - 1.0
    net = gross - rules.round_trip_cost_pct
    return {
        "stock_id": stock_id, "signal_date": as_of_date, "entry_date": str(entry["date"]),
        "entry_price": round(entry_price, 4), "exit_price": round(exit_price, 4),
        "exit_reason": exit_reason, "hold_days": int(hold_days),
        "net_return": round(net, 6),
    }


def _metrics(returns: list[float]) -> dict[str, Any]:
    s = pd.Series([r for r in returns if r is not None], dtype=float)
    if s.empty:
        return {"n": 0, "win_rate": None, "profit_factor": None, "avg": None, "median": None, "pct_gt20": None, "pct_gt50": None}
    pos, neg = s[s > 0].sum(), -s[s < 0].sum()
    return {
        "n": int(len(s)),
        "win_rate": round(float((s > 0).mean()), 3),
        "profit_factor": (round(float(pos / neg), 3) if neg > 0 else float("inf")),
        "avg": round(float(s.mean()), 4),
        "median": round(float(s.median()), 4),
        "pct_gt20": round(float((s >= 0.20).mean()), 3),
        "pct_gt50": round(float((s >= 0.50).mean()), 3),
    }


def _collect_trades(data_store, pit_store, params, candidates, dates, rules, turnover_floor=None) -> pd.DataFrame:
    market_cache: dict[str, Any] = {}
    rows: list[dict[str, Any]] = []
    for idx, as_of in enumerate(dates, start=1):
        universe = get_universe_as_of(as_of, data_store, turnover_floor=turnover_floor, candidate_symbols=candidates)
        if not universe:
            continue
        market = _market_features_for_entry(as_of, market=None, data_store=data_store, universe=universe, cache=market_cache)
        r60 = _universe_returns_as_of(data_store, universe, as_of, 60)
        r252 = _universe_returns_as_of(data_store, universe, as_of, 252)
        ushares = universe_shares_as_of(pit_store, universe, as_of)
        if idx == 1 or idx % 12 == 0:
            logger.info("swing %s/%s as_of=%s universe=%d trades=%d", idx, len(dates), as_of, len(universe), len(rows))
        for symbol in universe:
            try:
                detail, fin, filing = build_pit_inputs(symbol, as_of, pit_store)
                result = build_screening_result(
                    symbol, as_of, store=data_store, market=market, fin_metrics=fin, detail=detail,
                    universe_returns_60d=r60, universe_returns_252d=r252,
                    event_window_active=False, eps_filing_date=filing, n_pillar_analysis=None,
                    universe_shares=ushares,
                )
                full = build_full_result(result, params=params)
            except Exception:
                continue
            if full.pass_status != rules.entry_pass_status:
                continue
            trade = simulate_swing_trade(data_store, symbol, as_of, rules)
            if trade is None:
                continue
            trade["regime"] = result.market_regime
            trade["grade"] = full.grade
            rows.append(trade)
    return pd.DataFrame(rows)


def run_swing_backtest(
    *,
    run_id: str = "canslim_swing_v1",
    ohlcv_db_path: Path | str = DEFAULT_DB_PATH,
    pit_db_path: Path | str = DEFAULT_PIT_DB_PATH,
    start_date: str = "2011-01-01",
    end_date: str = "2025-12-31",
    cadence_days: int = 21,
    output_dir: Path | str = "artifacts/canslim_swing",
    candidate_symbols: list[str] | None = None,
    turnover_floor: float | None = None,
) -> SwingReport:
    started = time.time()
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    trades_csv = out_dir / "swing_trades.csv"
    json_path = out_dir / "swing_summary.json"
    md_path = out_dir / "swing_summary.md"

    params = load_params()
    rules = SwingRules.from_params(params)
    candidates = candidate_symbols or fundamentals_covered_symbols(pit_db_path)
    # Cross-sectional RS (L pillar) and breadth need a realistic universe. A tiny
    # candidate list makes RS percentiles degenerate -> grade rarely reaches A ->
    # near-zero PASS entries (an artifact, not a real signal). Warn loudly.
    if len(candidates) < 50:
        logger.warning(
            "swing backtest universe is only %d symbols — cross-sectional RS/breadth will be "
            "degenerate and PASS entries may be artificially ~0. Use a realistic universe "
            "(e.g. --universe-source tech, hundreds of names).", len(candidates),
        )
    data_store = CachedHistoricalDataStore(
        ohlcv_db_path, universe=[*candidates, "TAIEX", "TPEX"], start_date=start_date, end_date=end_date,
        lookback_buffer_days=500, forward_buffer_days=200,
    )
    pit_store = CachedPitFundamentalsStore(pit_db_path, universe=candidates)
    dates = cadence_grid(data_store, start_date, end_date, cadence_days=cadence_days)
    df = _collect_trades(data_store, pit_store, params, candidates, dates, rules, turnover_floor)

    df.to_csv(trades_csv, index=False, encoding="utf-8-sig")
    overall = _metrics(df["net_return"].tolist() if not df.empty else [])
    by_regime = {}
    if not df.empty:
        for reg in sorted(df["regime"].dropna().unique()):
            by_regime[reg] = _metrics(df[df["regime"] == reg]["net_return"].tolist())
    report = SwingReport(
        run_id=run_id, start_date=start_date, end_date=end_date, cadence_days=cadence_days,
        candidate_symbols=len(candidates), n_trades=int(len(df)), rules=asdict(rules),
        overall=overall, by_regime=by_regime,
        trades_csv=str(trades_csv), summary_json=str(json_path), summary_md=str(md_path),
        elapsed_seconds=round(time.time() - started, 1),
    )
    _write_report(report, json_path, md_path)
    logger.info("swing backtest done: %d trades, %s", report.n_trades, md_path)
    return report


def _fmt(m: dict[str, Any]) -> str:
    if not m.get("n"):
        return "n=0"
    return (f"n={m['n']} WR={m['win_rate']:.0%} PF={m['profit_factor']} "
            f"avg={m['avg']:+.2%} med={m['median']:+.2%} >20%={m['pct_gt20']:.0%} >50%={m['pct_gt50']:.0%}")


def _write_report(report: SwingReport, json_path: Path, md_path: Path) -> None:
    json_path.write_text(json.dumps(asdict(report), ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        f"# CANSLIM swing backtest: {report.run_id}",
        "",
        f"Period {report.start_date}..{report.end_date} | cadence {report.cadence_days}d | "
        f"{report.candidate_symbols} candidates | {report.n_trades} trades | {report.elapsed_seconds:.0f}s",
        f"Entry: pass_status=={report.rules['entry_pass_status']}. "
        f"Exit: stop {report.rules['stop_pct']:.0%} / close<MA{report.rules['exit_ma_days']} / "
        f"target {report.rules['target_pct']:.0%} / max-hold {report.rules['max_hold_days']}d. "
        f"Cost {report.rules['round_trip_cost_pct']:.3%} round-trip. Fixed params, by-regime.",
        "",
        "## Overall",
        f"- {_fmt(report.overall)}",
        "",
        "## By regime (bear-year drawdown is the known risk)",
    ]
    for reg, m in report.by_regime.items():
        lines.append(f"- {reg}: {_fmt(m)}")
    md_path.write_text("\n".join(lines), encoding="utf-8")
