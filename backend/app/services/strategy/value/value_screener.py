"""優質長期持有股票篩選器 — 三大面 (基本面 / 籌碼面 / 技術面).

Screens the PIT-safe canonical stores (backend/historical_data.db +
backend/pit_fundamentals.db) for quality long-term-hold candidates. Pure
research / watchlist tooling: the output is a screening grade + factor
breakdown only — never a trade instruction.

三大面 (each face scores 0-100, or ``None`` when its data is missing):

1. 基本面 (fundamental, weight ~50%): the Phase-0 value factors —
   Piotroski F-Score (quality), Magic Formula EY/ROC (cheap + productive),
   Shareholder Yield (capital return). Reuses ``value_factors`` verbatim.
2. 籌碼面 (chips, ~25%): foreign + trust institutional net-buy persistence
   over a lookback window (sustained accumulation, not one-day spikes).
3. 技術面 (technical, ~25%): long-term trend structure — close above the
   long MA, proximity to the 52-week high. Deliberately gentle: a long-hold
   screen rewards an intact uptrend, it does not chase momentum.

Design rules (binding, same as the rest of the value package):
- Missing data → that face/component is ``None``, recorded in
  ``data_quality_flags``, and lowers ``confidence_score``. Never fabricated.
- A symbol with no usable fundamentals can never be graded above 資料不足.
- All thresholds/weights live in the YAML ``value.screener`` block.
- Output strings are verb-free conditions (no buy/sell/hold language).
- Factor edge is NOT yet validated on the full 2011-2025 cohort run; until
  the user's ``run_value_cohort`` decision gate passes, this is a research
  watchlist, and the report says so.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass
from datetime import date as _date
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from backend.app.services.backtest.historical_data_store import (
    CachedHistoricalDataStore,
    DEFAULT_DB_PATH,
)
from backend.app.services.backtest.pit_fundamentals_store import (
    CachedPitFundamentalsStore,
    DEFAULT_PIT_DB_PATH,
)
from backend.app.services.strategy.canslim.params import load_params
from backend.app.services.strategy.canslim.pit_universe import get_universe_as_of
from backend.app.services.strategy.value.value_cohort import _market_cap
from backend.app.services.strategy.value.value_factors import (
    _value_cfg,
    magic_formula,
    piotroski_fscore,
    shareholder_yield,
)

logger = logging.getLogger(__name__)

# Verb-free screening grades (conditions, never instructions).
GRADE_CORE = "核心觀察"      # composite high AND F-Score in the high-quality band
GRADE_WATCH = "觀察"         # composite above the watch floor
GRADE_BELOW = "未達標準"     # screened, composite below the watch floor
GRADE_NO_DATA = "資料不足"   # fundamentals unavailable — cannot be graded
GRADES = (GRADE_CORE, GRADE_WATCH, GRADE_BELOW, GRADE_NO_DATA)

DISCLAIMER = "本分析僅供參考，不構成投資建議。"


def _screener_cfg(params: Mapping[str, Any]) -> Mapping[str, Any]:
    cfg = _value_cfg(params).get("screener", {})
    return cfg if isinstance(cfg, Mapping) else {}


def _clamp01(x: float) -> float:
    return min(1.0, max(0.0, x))


# ── 基本面 ────────────────────────────────────────────────────────────────────
def fundamental_face(
    *,
    financials: pd.DataFrame | None,
    balance_sheet: pd.DataFrame | None,
    cash_flow: pd.DataFrame | None,
    per: pd.DataFrame | None,
    market_cap: float | None,
    params: Mapping[str, Any],
) -> dict:
    """Compose the three Phase-0 value factors into one 0-100 fundamental score.

    Component values ramp linearly up to their YAML attractiveness threshold
    (e.g. EY of 0.05 vs ``ey_attractive_min`` 0.10 → half credit); the score is
    the available-weight-normalized mean. No component → score ``None``.
    """
    vcfg = _value_cfg(params)
    cfg = _screener_cfg(params)
    flags: list[str] = []

    fscore = piotroski_fscore(
        financials=financials, balance_sheet=balance_sheet, cash_flow=cash_flow, params=params
    )
    mf = magic_formula(
        financials=financials, balance_sheet=balance_sheet, market_cap=market_cap, params=params
    )
    sy = shareholder_yield(
        balance_sheet=balance_sheet, per=per, market_cap=market_cap, params=params
    )

    ey_min = float(vcfg.get("ey_attractive_min", 0.10))
    roc_min = float(vcfg.get("roc_quality_min", 0.20))
    sy_min = float(vcfg.get("shareholder_yield_strong_min", 0.05))
    weights = {
        "fscore": float(cfg.get("comp_weight_fscore", 0.4)),
        "ey": float(cfg.get("comp_weight_ey", 0.2)),
        "roc": float(cfg.get("comp_weight_roc", 0.2)),
        "sy": float(cfg.get("comp_weight_sy", 0.2)),
    }

    comps: dict[str, float] = {}
    if fscore is not None:
        comps["fscore"] = _clamp01(fscore / 9.0)
    else:
        flags.append("fscore_unavailable")
    if mf["ey"] is not None and ey_min > 0:
        comps["ey"] = _clamp01(mf["ey"] / ey_min)
    else:
        flags.append("ey_unavailable")
    if mf["roc"] is not None and roc_min > 0:
        comps["roc"] = _clamp01(mf["roc"] / roc_min)
    else:
        flags.append("roc_unavailable")
    if sy["total"] is not None and sy_min > 0:
        comps["sy"] = _clamp01(sy["total"] / sy_min)
    else:
        flags.append("shareholder_yield_unavailable")

    score: float | None = None
    if comps:
        wsum = sum(weights[k] for k in comps)
        if wsum > 0:
            score = round(100.0 * sum(weights[k] * v for k, v in comps.items()) / wsum, 1)
    else:
        flags.append("fundamentals_unavailable")

    # Upstream missing-input detail (transparency + confidence haircut).
    missing_inputs = list(dict.fromkeys([*mf["missing"], *sy["missing"]]))
    return {
        "score": score,
        "fscore": fscore,
        "ey": mf["ey"],
        "roc": mf["roc"],
        "sy_total": sy["total"],
        "diluted": sy["diluted"],
        "missing_inputs": missing_inputs,
        "flags": flags,
    }


# ── 籌碼面 ────────────────────────────────────────────────────────────────────
def chips_face(institutional: pd.DataFrame | None, params: Mapping[str, Any]) -> dict:
    """Foreign + trust net-buy persistence: fraction of days the combined daily
    net is positive (70%) + whether the cumulative window net is positive (30%).
    Rewards sustained accumulation rather than single-day spikes."""
    cfg = _screener_cfg(params)
    min_days = int(cfg.get("chips_min_days", 20))
    out: dict[str, Any] = {"score": None, "inst_persistence": None, "inst_cumulative_net": None, "flags": []}
    if institutional is None or institutional.empty:
        out["flags"].append("institutional_missing")
        return out
    cols = [c for c in ("foreign_net", "trust_net") if c in institutional.columns]
    if not cols:
        out["flags"].append("institutional_missing")
        return out
    daily = institutional[cols].apply(pd.to_numeric, errors="coerce").sum(axis=1, min_count=1).dropna()
    if len(daily) < min_days:
        out["flags"].append("institutional_history_thin")
        return out
    persistence = float((daily > 0).mean())
    cumulative = float(daily.sum())
    out["inst_persistence"] = round(persistence, 3)
    out["inst_cumulative_net"] = cumulative
    out["score"] = round((0.7 * persistence + 0.3 * (1.0 if cumulative > 0 else 0.0)) * 100.0, 1)
    return out


# ── 技術面 ────────────────────────────────────────────────────────────────────
def technical_face(bars: pd.DataFrame | None, params: Mapping[str, Any]) -> dict:
    """Long-term trend structure: close above the long MA (60%) + proximity to
    the 52-week high (40%, linear ramp between the deep/near YAML bands)."""
    cfg = _screener_cfg(params)
    ma_days = int(cfg.get("tech_ma_days", 200))
    near = float(cfg.get("tech_near_high_pct", -0.10))
    deep = float(cfg.get("tech_deep_below_pct", -0.40))
    out: dict[str, Any] = {"score": None, "above_long_ma": None, "pct_from_52w_high": None, "flags": []}
    closes = (
        pd.to_numeric(bars["close"], errors="coerce").dropna()
        if bars is not None and not bars.empty and "close" in bars.columns
        else pd.Series(dtype=float)
    )
    if len(closes) < ma_days:
        out["flags"].append("ohlcv_history_thin")
        return out
    close = float(closes.iloc[-1])
    long_ma = float(closes.iloc[-ma_days:].mean())
    high = float(closes.max())
    if close <= 0 or high <= 0:
        out["flags"].append("ohlcv_history_thin")
        return out
    pct_from_high = close / high - 1.0
    trend = 1.0 if close > long_ma else 0.0
    proximity = _clamp01((pct_from_high - deep) / (near - deep)) if near > deep else 0.0
    out["above_long_ma"] = close > long_ma
    out["pct_from_52w_high"] = round(pct_from_high, 4)
    out["score"] = round((0.6 * trend + 0.4 * proximity) * 100.0, 1)
    return out


# ── composite + grade ─────────────────────────────────────────────────────────
def composite_grade(fund: dict, chips: dict, tech: dict, params: Mapping[str, Any]) -> dict:
    """Weight the three faces into a composite 0-100, renormalizing over the
    faces that have data. Fundamentals are mandatory: without them the symbol
    is 資料不足, never graded. Confidence drops per missing face/input."""
    cfg = _screener_cfg(params)
    vcfg = _value_cfg(params)
    weights = {
        "fundamental": float(cfg.get("weight_fundamental", 0.5)),
        "chips": float(cfg.get("weight_chips", 0.25)),
        "technical": float(cfg.get("weight_technical", 0.25)),
    }
    scores = {"fundamental": fund["score"], "chips": chips["score"], "technical": tech["score"]}
    flags = [*fund["flags"], *chips["flags"], *tech["flags"]]
    missing_faces = [name for name, s in scores.items() if s is None]
    flags.extend(f"{name}_face_missing" for name in missing_faces)

    total: float | None = None
    if fund["score"] is None:
        grade = GRADE_NO_DATA
    else:
        avail = {k: s for k, s in scores.items() if s is not None}
        wsum = sum(weights[k] for k in avail)
        total = round(sum(weights[k] * s for k, s in avail.items()) / wsum, 1) if wsum > 0 else None
        core_min = float(cfg.get("grade_core_total_min", 75))
        watch_min = float(cfg.get("grade_watch_total_min", 60))
        fscore_hi = int(vcfg.get("fscore_high_quality_min", 8))
        if (
            total is not None
            and total >= core_min
            and fund["fscore"] is not None
            and fund["fscore"] >= fscore_hi
        ):
            grade = GRADE_CORE
        elif total is not None and total >= watch_min:
            grade = GRADE_WATCH
        else:
            grade = GRADE_BELOW

    confidence = 100 - 20 * len(missing_faces) - 3 * len(fund["missing_inputs"]) - 3 * len(fund["flags"])
    return {
        "total_score": total,
        "screening_grade": grade,
        "confidence_score": max(10, confidence),
        "data_quality_flags": list(dict.fromkeys(flags)),
    }


# ── per-symbol screen ─────────────────────────────────────────────────────────
def screen_symbol_value(data_store, pit_store, params, symbol: str, as_of: str) -> dict:
    """Screen one symbol at as_of across the three faces. Always returns a row
    (ungradable symbols come back as 資料不足); never fabricates a value."""
    cfg = _screener_cfg(params)
    lookback_bars = max(252, int(cfg.get("tech_ma_days", 200))) + 10
    chips_days = int(cfg.get("chips_lookback_days", 60))

    fin = pit_store.get_financials_as_of(symbol, as_of, limit=12)
    bs = pit_store.get_balance_sheet_as_of(symbol, as_of, limit=8)
    cf = pit_store.get_cash_flow_as_of(symbol, as_of, limit=8)
    per = pit_store.get_per_as_of(symbol, as_of, limit=60)
    inst = pit_store.get_institutional_as_of(symbol, as_of, limit=chips_days)
    mc = _market_cap(data_store, pit_store, symbol, as_of)
    bars = data_store.get_ohlcv_as_of(symbol, as_of, lookback_bars)

    fund = fundamental_face(
        financials=fin, balance_sheet=bs, cash_flow=cf, per=per, market_cap=mc, params=params
    )
    chips = chips_face(inst, params)
    tech = technical_face(bars, params)
    comp = composite_grade(fund, chips, tech, params)

    return {
        "stock_id": symbol,
        "as_of_date": as_of,
        "screening_grade": comp["screening_grade"],
        "total_score": comp["total_score"],
        "fundamental_score": fund["score"],
        "chips_score": chips["score"],
        "technical_score": tech["score"],
        "fscore": fund["fscore"],
        "ey": fund["ey"],
        "roc": fund["roc"],
        "shareholder_yield": fund["sy_total"],
        "inst_persistence": chips["inst_persistence"],
        "above_long_ma": tech["above_long_ma"],
        "pct_from_52w_high": tech["pct_from_52w_high"],
        "market_cap": mc,
        "confidence_score": comp["confidence_score"],
        "data_quality_flags": ";".join(comp["data_quality_flags"]),
    }


# ── universe run + report ─────────────────────────────────────────────────────
@dataclass
class ValueScreenReport:
    run_id: str
    as_of: str
    candidate_symbols: int
    universe_size: int
    n_rows: int
    grade_counts: dict[str, int]
    rows_csv: str
    report_md: str
    elapsed_seconds: float = 0.0


def run_value_screen(
    *,
    as_of: str | None = None,
    run_id: str | None = None,
    ohlcv_db_path: Path | str = DEFAULT_DB_PATH,
    pit_db_path: Path | str = DEFAULT_PIT_DB_PATH,
    output_dir: Path | str = "artifacts/value_screen",
    candidate_symbols: list[str],
    turnover_floor: float | None = 50_000_000,
    max_staleness_days: int | None = 10,
    top_n: int = 50,
) -> ValueScreenReport:
    """Screen the PIT liquidity universe at as_of (default: latest TAIEX bar) and
    write a ranked watchlist CSV + markdown report. The liquidity floor and
    staleness cut are the junk filter: illiquid / no-longer-trading names never
    reach grading."""
    started = time.time()
    run_id = run_id or "value_screen"
    candidates = list(candidate_symbols)
    anchor = as_of or _date.today().isoformat()
    data_store = CachedHistoricalDataStore(
        ohlcv_db_path, universe=[*candidates, "TAIEX"],
        start_date=anchor, end_date=anchor,
        lookback_buffer_days=460, forward_buffer_days=0,
    )
    if as_of is None:
        taiex = data_store.get_ohlcv_as_of("TAIEX", anchor, 1)
        if taiex is not None and not taiex.empty:
            as_of = str(taiex["date"].iloc[-1])[:10]
        else:
            as_of = anchor
            logger.warning("no TAIEX bar found <= %s; using it as as_of anyway", anchor)
    pit_store = CachedPitFundamentalsStore(pit_db_path, universe=candidates)
    params = load_params()

    universe = get_universe_as_of(
        as_of, data_store, turnover_floor=turnover_floor,
        candidate_symbols=candidates, max_staleness_days=max_staleness_days,
    )
    logger.info("value screen as_of=%s: %d candidates -> %d in PIT liquidity universe",
                as_of, len(candidates), len(universe))

    rows: list[dict[str, Any]] = []
    for symbol in universe:
        try:
            rows.append(screen_symbol_value(data_store, pit_store, params, symbol, as_of))
        except Exception as exc:  # one symbol must never abort the screen
            logger.debug("screen failed %s @ %s: %s", symbol, as_of, exc)
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(
            ["total_score", "confidence_score"], ascending=[False, False], na_position="last"
        ).reset_index(drop=True)
        graded = df["total_score"].notna()
        df["watchlist_priority"] = None
        df.loc[graded, "watchlist_priority"] = range(1, int(graded.sum()) + 1)

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows_csv = out_dir / f"{run_id}_{as_of}_rows.csv"
    report_md = out_dir / f"{run_id}_{as_of}_report.md"
    df.to_csv(rows_csv, index=False, encoding="utf-8-sig")

    grade_counts = (
        {str(k): int(v) for k, v in df["screening_grade"].value_counts().items()} if not df.empty else {}
    )
    report = ValueScreenReport(
        run_id=run_id, as_of=as_of, candidate_symbols=len(candidates),
        universe_size=len(universe), n_rows=int(len(df)), grade_counts=grade_counts,
        rows_csv=str(rows_csv), report_md=str(report_md),
        elapsed_seconds=round(time.time() - started, 1),
    )
    _write_screen_report(report, df, top_n, report_md)
    logger.info("value screen done: %d rows, %s", report.n_rows, report_md)
    return report


def _num(v: Any, fmt: str = "{:.1f}") -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "-"
    return fmt.format(v)


def _write_screen_report(report: ValueScreenReport, df: pd.DataFrame, top_n: int, path: Path) -> None:
    lines = [
        f"# 優質長期持有篩選 (三大面): {report.run_id} @ {report.as_of}",
        "",
        f"候選 {report.candidate_symbols} 檔 → PIT 流動性母體 {report.universe_size} 檔 → "
        f"評分 {report.n_rows} 列 | {report.elapsed_seconds:.0f}s",
        "",
        "三大面 = 基本面 (F-Score / Magic Formula / 股東殖利率) × 籌碼面 (外資+投信買超持續性) × "
        "技術面 (長期趨勢結構)。等級為篩選觀察分級，非任何操作指示。",
        "",
        "## 等級分布",
    ]
    for g in GRADES:
        lines.append(f"- {g}: {report.grade_counts.get(g, 0)}")
    lines += ["", f"## 觀察名單 (前 {top_n})", ""]
    header = ("| # | 代號 | 等級 | 總分 | 基本面 | 籌碼面 | 技術面 | F-Score | EY | ROC | 股東殖利率 "
              "| 法人持續性 | 距52週高 | 信心 | 資料品質 |")
    lines += [header, "|" + "---|" * 15]
    shown = df[df["total_score"].notna()].head(top_n) if not df.empty else df
    for _, r in shown.iterrows():
        lines.append(
            f"| {r['watchlist_priority']} | {r['stock_id']} | {r['screening_grade']} "
            f"| {_num(r['total_score'])} | {_num(r['fundamental_score'])} | {_num(r['chips_score'])} "
            f"| {_num(r['technical_score'])} | {_num(r['fscore'], '{:.0f}')} "
            f"| {_num(r['ey'], '{:.3f}')} | {_num(r['roc'], '{:.3f}')} "
            f"| {_num(r['shareholder_yield'], '{:.3f}')} | {_num(r['inst_persistence'], '{:.2f}')} "
            f"| {_num(r['pct_from_52w_high'], '{:+.1%}')} | {_num(r['confidence_score'], '{:.0f}')} "
            f"| {r['data_quality_flags'] or '-'} |"
        )
    lines += [
        "",
        "## 注意事項",
        "- 權重與門檻為 v1 假設 (YAML `value.screener`)；F-Score 等因子的報酬優勢尚未在 2011-2025 "
        "全量 PIT 驗證 (`run_value_cohort`) 通過決策閘門前，本清單僅屬研究/觀察名單工具。",
        "- 缺資料的面向不計分並降低信心分數，不以估計值填補。",
        f"- {DISCLAIMER}",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    # JSON sidecar for programmatic use.
    path.with_suffix(".json").write_text(
        json.dumps(asdict(report), ensure_ascii=False, indent=2), encoding="utf-8"
    )
