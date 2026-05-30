"""Composite Durability Score (Path B — durable-quality screening).

Measures how DURABLE a company's profitability is — the trait that (per the quality-factor
research) should give smaller crash drawdowns, faster recovery, and near-zero delisting. This
is an ADDITIVE measurement layer: it does NOT change any validated signal/score/grade math and
emits no buy/sell language — it returns a 0-100 score + per-component breakdown for screening
and for the crash-resilience cohort (crash_resilience.py).

Self-contained: reads the same PIT DataFrames the screener uses (financials, balance_sheet,
institutional) and the already-computed `fin_metrics`/`detail` from pit_inputs. PIT-safe — the
caller passes frames gated to `as_of` (filing_date <= as_of). Missing inputs lower confidence
(component omitted from the weighted mean), never fabricated.

Components (YAML `durability:` block, tunable):
1. op_margin_stability  — low coefficient-of-variation of quarterly operating margin (pricing power)
2. roe_quality          — ROE level + TTM-vs-latest-annual EPS (no profitability break)
3. multiyear_consistency— >=N years of positive, above-floor annual-EPS growth
4. earnings_purity      — operating income drives net income (strip 業外/one-off)
5. inst_continuity       — sustained foreign+trust net-buy / no mass distribution (flow proxy)
6. partial_fscore       — 7 of Piotroski's 9 (the 2 cash-flow points deferred until CFO data)
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any, Mapping

import pandas as pd

from backend.app.services.strategy.canslim.pit_inputs import _raw_line_items

# Income-statement (per-quarter) line items.
_REV, _OPI, _GP, _NI, _PTI = (
    "Revenue", "OperatingIncome", "GrossProfit", "IncomeAfterTaxes", "PreTaxIncome",
)
# Balance-sheet line items (TotalLiabilitiesEquity == total assets in FinMind TW).
_TA, _CA, _CL, _CAP = ("TotalLiabilitiesEquity", "CurrentAssets", "CurrentLiabilities", "CapitalStock")
_LT_DEBT = ("LongtermBorrowings", "BondsPayable")


@dataclass(frozen=True)
class DurabilityResult:
    score: int                       # 0-100 weighted mean of available components (else 0)
    components: dict[str, float]     # component -> sub-score 0-1
    missing: list[str] = field(default_factory=list)
    fscore: int | None = None        # partial Piotroski (0-7), informational


def compute_durability(
    *,
    fin_metrics: Mapping[str, Any] | None,
    detail: Mapping[str, Any] | None,
    financials: pd.DataFrame | None,
    balance_sheet: pd.DataFrame | None,
    params: Mapping[str, Any],
) -> DurabilityResult:
    cfg = params.get("durability", {}) if isinstance(params, Mapping) else {}
    weights: dict[str, float] = dict(cfg.get("weights", {}))
    fin_metrics = fin_metrics or {}
    detail = detail or {}
    inc = _periodic_items(financials)          # sorted [(period, items)]
    bs = _periodic_items(balance_sheet)

    comps: dict[str, float] = {}
    missing: list[str] = []

    _set(comps, missing, "op_margin_stability", _op_margin_stability(inc, cfg))
    _set(comps, missing, "roe_quality", _roe_quality(fin_metrics, cfg))
    _set(comps, missing, "multiyear_consistency", _multiyear_consistency(fin_metrics, cfg))
    _set(comps, missing, "earnings_purity", _earnings_purity(inc, cfg))
    _set(comps, missing, "inst_continuity", _inst_continuity(detail, cfg))
    fscore, fscore_sub = _partial_fscore(inc, bs, cfg)
    _set(comps, missing, "partial_fscore", fscore_sub)

    if not comps:
        return DurabilityResult(score=0, components={}, missing=missing, fscore=fscore)
    total_w = sum(float(weights.get(k, 1.0)) for k in comps)
    acc = sum(float(weights.get(k, 1.0)) * v for k, v in comps.items())
    score = int(round(100.0 * acc / total_w)) if total_w > 0 else 0
    return DurabilityResult(score=score, components=comps, missing=missing, fscore=fscore)


# ── components ────────────────────────────────────────────────────────────────
def _op_margin_stability(inc: list[tuple[str, dict]], cfg: Mapping[str, Any]) -> float | None:
    """Low CV of quarterly operating margin = durable pricing power. Needs a positive mean."""
    n = int(cfg.get("op_margin_quarters", 12))
    margins = []
    for _, it in inc[-n:]:
        rev, opi = it.get(_REV), it.get(_OPI)
        if rev and rev > 0 and opi is not None:
            margins.append(opi / rev)
    if len(margins) < int(cfg.get("op_margin_min_quarters", 6)):
        return None
    mean = statistics.fmean(margins)
    if mean <= 0:
        return 0.0
    cv = statistics.pstdev(margins) / mean
    lo = float(cfg.get("op_cv_excellent", 0.15))   # CV <= lo -> 1.0
    hi = float(cfg.get("op_cv_poor", 0.60))         # CV >= hi -> 0.0
    return _ramp_down(cv, lo, hi)


def _roe_quality(fin_metrics: Mapping[str, Any], cfg: Mapping[str, Any]) -> float | None:
    roe = _f(fin_metrics.get("roe"))
    if roe is None:
        return None
    floor = float(cfg.get("roe_floor", 0.10))
    target = float(cfg.get("roe_target", 0.20))
    level = _ramp_up(roe, floor, target)
    # No profitability break: TTM EPS >= latest full-year EPS (not decelerating below last FY).
    ttm, fy = _f(fin_metrics.get("ttm_eps")), _f(fin_metrics.get("latest_fy_eps"))
    if ttm is not None and fy is not None and fy != 0:
        trend = 1.0 if ttm >= fy else max(0.0, ttm / fy)
        return 0.7 * level + 0.3 * trend
    return level


def _multiyear_consistency(fin_metrics: Mapping[str, Any], cfg: Mapping[str, Any]) -> float | None:
    annual = fin_metrics.get("annual_eps")
    if not annual or len(annual) < 2:
        return None
    series = [v for v in annual if v is not None]
    if len(series) < 2:
        return None
    floor = float(cfg.get("annual_growth_floor", 0.0))
    good = 0
    pairs = 0
    for prev, cur in zip(series[:-1], series[1:]):
        pairs += 1
        if prev is not None and cur is not None and prev > 0 and (cur / prev - 1.0) >= floor and cur > 0:
            good += 1
    return good / pairs if pairs else None


def _earnings_purity(inc: list[tuple[str, dict]], cfg: Mapping[str, Any]) -> float | None:
    """Operating income should drive net income; penalize 業外/one-off-driven earnings.
    purity = TTM OperatingIncome / TTM IncomeAfterTaxes, clipped to [0,1]."""
    opi = _ttm(inc, _OPI)
    ni = _ttm(inc, _NI)
    if opi is None or ni is None or ni <= 0:
        return None
    ratio = opi / ni
    floor = float(cfg.get("purity_floor", 0.5))    # ratio <= floor -> 0 (earnings not from core ops)
    return max(0.0, min(1.0, (ratio - floor) / (1.0 - floor))) if ratio < 1.0 else 1.0


def _inst_continuity(detail: Mapping[str, Any], cfg: Mapping[str, Any]) -> float | None:
    """Sustained foreign+trust accumulation / no mass distribution (flow proxy for holding-%
    continuity). Score = fraction of recent days with non-negative combined net flow."""
    fseries = detail.get("foreign_net_5") or []
    tseries = detail.get("trust_net_5") or []
    combined = []
    for i in range(max(len(fseries), len(tseries))):
        f = fseries[i] if i < len(fseries) else 0.0
        t = tseries[i] if i < len(tseries) else 0.0
        f = f if isinstance(f, (int, float)) else 0.0
        t = t if isinstance(t, (int, float)) else 0.0
        combined.append(f + t)
    if not combined:
        return None
    non_neg = sum(1 for v in combined if v >= 0)
    cum = sum(combined)
    frac = non_neg / len(combined)
    # Reward sustained non-negative flow; require net-positive cumulative for the top band.
    return frac if cum >= 0 else max(0.0, frac - 0.3)


def _partial_fscore(inc: list[tuple[str, dict]], bs: list[tuple[str, dict]], cfg: Mapping[str, Any]) -> tuple[int | None, float | None]:
    """7 of Piotroski's 9 signals (the 2 cash-flow points need CFO, deferred). Returns
    (raw 0-7, sub-score 0-1). None when there isn't enough history (need ~8 quarters + 2 BS)."""
    roa = _roa(inc, bs, 0)
    roa_prev = _roa(inc, bs, 4)
    cr = _ratio(bs, 0, _CA, _CL)
    cr_prev = _ratio(bs, 1, _CA, _CL)
    at = _asset_turnover(inc, bs, 0)
    at_prev = _asset_turnover(inc, bs, 4)
    gm = _gross_margin(inc, 0)
    gm_prev = _gross_margin(inc, 4)
    ltd = _lt_debt(bs, 0)
    ltd_prev = _lt_debt(bs, 1)
    cap = _bs_val(bs, 0, _CAP)
    cap_prev = _bs_val(bs, 1, _CAP)

    checks: list[bool | None] = [
        None if roa is None else (roa > 0),                                          # profitable on assets
        None if (roa is None or roa_prev is None) else (roa > roa_prev),             # improving ROA
        None if (cr is None or cr_prev is None) else (cr > cr_prev),                 # liquidity up
        None if (ltd is None or ltd_prev is None) else (ltd <= ltd_prev),            # leverage not rising
        None if (cap is None or cap_prev is None) else (cap <= cap_prev * 1.001),    # no dilution
        None if (gm is None or gm_prev is None) else (gm > gm_prev),                 # margin up
        None if (at is None or at_prev is None) else (at > at_prev),                 # asset turnover up
    ]
    usable = [c for c in checks if c is not None]
    if len(usable) < int(cfg.get("fscore_min_checks", 4)):
        return None, None
    raw = sum(1 for c in usable if c)
    return raw, raw / len(usable)


# ── parsing / math helpers ──────────────────────────────────────────────────
def _periodic_items(df: pd.DataFrame | None) -> list[tuple[str, dict]]:
    if df is None or df.empty or "raw_json" not in df.columns:
        return []
    out: list[tuple[str, dict]] = []
    for _, row in df.sort_values("period_end").iterrows():
        out.append((str(row.get("period_end"))[:10], _raw_line_items(row.get("raw_json"))))
    return out


def _ttm(inc: list[tuple[str, dict]], key: str, end_back: int = 0) -> float | None:
    """Sum the 4 quarters ending `end_back` quarters before the latest (per-quarter flows)."""
    if len(inc) < 4 + end_back:
        return None
    window = inc[len(inc) - 4 - end_back: len(inc) - end_back]
    vals = [it.get(key) for _, it in window if it.get(key) is not None]
    return sum(vals) if len(vals) == 4 else None


def _roa(inc, bs, q_back: int) -> float | None:
    ni = _ttm(inc, _NI, q_back)
    ta = _bs_val(bs, q_back // 4, _TA)
    return ni / ta if ni is not None and ta and ta > 0 else None


def _asset_turnover(inc, bs, q_back: int) -> float | None:
    rev = _ttm(inc, _REV, q_back)
    ta = _bs_val(bs, q_back // 4, _TA)
    return rev / ta if rev is not None and ta and ta > 0 else None


def _gross_margin(inc, q_back: int) -> float | None:
    gp = _ttm(inc, _GP, q_back)
    rev = _ttm(inc, _REV, q_back)
    return gp / rev if gp is not None and rev and rev > 0 else None


def _ratio(bs, idx_back: int, num: str, den: str) -> float | None:
    n = _bs_val(bs, idx_back, num)
    d = _bs_val(bs, idx_back, den)
    return n / d if n is not None and d and d > 0 else None


def _lt_debt(bs, idx_back: int) -> float | None:
    parts = [_bs_val(bs, idx_back, k) for k in _LT_DEBT]
    parts = [p for p in parts if p is not None]
    return sum(parts) if parts else None


def _bs_val(bs: list[tuple[str, dict]], idx_back: int, key: str) -> float | None:
    if len(bs) <= idx_back:
        return None
    return bs[len(bs) - 1 - idx_back][1].get(key)


def _ramp_up(x: float, lo: float, hi: float) -> float:
    if hi <= lo:
        return 1.0 if x >= hi else 0.0
    return max(0.0, min(1.0, (x - lo) / (hi - lo)))


def _ramp_down(x: float, lo: float, hi: float) -> float:
    if hi <= lo:
        return 1.0 if x <= lo else 0.0
    return max(0.0, min(1.0, (hi - x) / (hi - lo)))


def _f(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _set(comps: dict[str, float], missing: list[str], name: str, value: float | None) -> None:
    if value is None:
        missing.append(name)
    else:
        comps[name] = float(value)
