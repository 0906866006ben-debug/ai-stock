"""Value / quality / shareholder-return factor functions (Phase 0).

Three PIT-safe, pure factor calculators for the long-term value-quant system:

1. ``magic_formula``      — Greenblatt Earnings Yield (EBIT/EV) + Return on Capital.
2. ``piotroski_fscore``   — the full 0-9 Piotroski quality score (wraps the validated
                            ``durability._partial_fscore``, fed with cash flow for the 2 CFO points).
3. ``shareholder_yield``  — cash dividend + net buyback + net debt reduction.

Design rules (binding):
- **Pure**: every function takes already-fetched PIT DataFrames + scalars (market cap) and
  ``params`` (the YAML thresholds). No network, no store, no global state. The CALLER is
  responsible for fetching frames gated to ``as_of`` via ``PitFundamentalsStore.get_*_as_of``
  (``filing_date <= as_of``), which is what makes these functions PIT-safe.
- **Never fabricate**: a missing required input makes the factor (or sub-field) ``None`` and is
  recorded in a ``missing`` list. We never estimate or impute a value. The only exception is a
  *deduction* term that does not exist in the data (e.g. ``LongtermInvestments``), which is
  treated as 0 (a neutral, non-inflating default) AND recorded in ``missing`` for transparency.
- **Reuse, don't reinvent**: TTM sums, line-item parsing, the partial F-Score and balance-sheet
  helpers all come from ``durability.py`` / ``pit_inputs.py``.

FinMind ``raw_json`` key names confirmed against the live ``pit_fundamentals.db`` (2026-06):
balance_sheet uses ``CashAndCashEquivalents`` (NOT "Cash"), ``PropertyPlantAndEquipment``,
``CurrentAssets``, ``CurrentLiabilities``, ``CapitalStock``, ``LongtermBorrowings``,
``ShorttermBorrowings``; ``BondsPayable`` and ``LongtermInvestments`` are NOT present in the data
and are therefore handled gracefully (debt term: optional add; NWC term: treated as 0 + recorded).
cash_flow CFO total = ``CashFlowsFromOperatingActivities`` (stored in the ``cfo`` column).
"""
from __future__ import annotations

from typing import Any, Mapping

import pandas as pd

from backend.app.services.strategy.canslim.durability import (
    _bs_val,
    _f,
    _latest_fy_cfo_ni,
    _partial_fscore,
    _periodic_items,
    _ramp_up,
    _ttm,
)

# Income-statement line item driving EBIT (FinMind per-quarter flow).
_OPI = "OperatingIncome"
# Balance-sheet line items (confirmed keys; see module docstring).
_CASH = "CashAndCashEquivalents"
_PPE = "PropertyPlantAndEquipment"
_CURR_ASSETS = "CurrentAssets"
_CAPITAL_STOCK = "CapitalStock"
_LONGTERM_INVEST = "LongtermInvestments"   # not in FinMind raw_json -> deduction treated as 0
_LT_DEBT = ("LongtermBorrowings", "BondsPayable")          # BondsPayable absent in data -> optional
_ST_DEBT = ("ShorttermBorrowings",)


def _value_cfg(params: Mapping[str, Any]) -> Mapping[str, Any]:
    return params.get("value", {}) if isinstance(params, Mapping) else {}


def _periods_back_index(cfg: Mapping[str, Any]) -> int:
    """Number of quarterly periods that constitute one year (for YoY balance-sheet deltas)."""
    return int(cfg.get("yoy_periods_back", 4))


# ── Magic Formula ─────────────────────────────────────────────────────────────
def magic_formula(
    *,
    financials: pd.DataFrame | None,
    balance_sheet: pd.DataFrame | None,
    market_cap: float | None,
    params: Mapping[str, Any],
) -> dict:
    """Greenblatt Magic Formula factors.

    ``EBIT`` = TTM OperatingIncome (4 quarters).
    ``EV``   = market_cap + long-term debt (LongtermBorrowings + BondsPayable) - cash.
    ``EY``   = EBIT / EV  (Earnings Yield; higher = cheaper).
    ``ROC``  = EBIT / (net fixed assets [PropertyPlantAndEquipment] +
                       net working capital [CurrentAssets - Cash - LongtermInvestments]).

    Returns ``{ey, roc, ebit, ev, missing}``. Any factor that cannot be computed from the
    available data is ``None`` and the responsible input is appended to ``missing``.
    """
    _value_cfg(params)  # reserved for future tunables; thresholds live in YAML
    inc = _periodic_items(financials)
    bs = _periodic_items(balance_sheet)
    missing: list[str] = []

    ebit = _ttm(inc, _OPI)
    if ebit is None:
        missing.append("ebit_ttm")

    cash = _bs_val(bs, 0, _CASH)
    if cash is None:
        missing.append(_CASH)

    # Long-term debt: sum of whichever long-debt lines are present (BondsPayable absent in data).
    lt_parts = [_bs_val(bs, 0, k) for k in _LT_DEBT]
    lt_parts = [p for p in lt_parts if p is not None]
    long_debt = sum(lt_parts) if lt_parts else None
    if long_debt is None:
        missing.append("long_debt")

    mc = _f(market_cap)
    if mc is None or mc <= 0:
        missing.append("market_cap")

    # Enterprise value (cash defaults to 0 only when genuinely absent, recorded above).
    ev = None
    if mc is not None and mc > 0:
        ev = mc + (long_debt or 0.0) - (cash or 0.0)

    ey = ebit / ev if (ebit is not None and ev not in (None, 0)) else None

    # Return on Capital denominator.
    ppe = _bs_val(bs, 0, _PPE)
    if ppe is None:
        missing.append(_PPE)
    curr_assets = _bs_val(bs, 0, _CURR_ASSETS)
    if curr_assets is None:
        missing.append(_CURR_ASSETS)
    lt_invest = _bs_val(bs, 0, _LONGTERM_INVEST)
    if lt_invest is None:
        # Genuinely not in FinMind data: a deduction treated as 0 (neutral, non-inflating), flagged.
        missing.append(_LONGTERM_INVEST)

    roc = None
    if ebit is not None and ppe is not None and curr_assets is not None:
        net_working_capital = curr_assets - (cash or 0.0) - (lt_invest or 0.0)
        capital = ppe + net_working_capital
        if capital and capital > 0:
            roc = ebit / capital

    return {"ey": ey, "roc": roc, "ebit": ebit, "ev": ev, "missing": missing}


# ── Piotroski F-Score ───────────────────────────────────────────────────────
def piotroski_fscore(
    *,
    financials: pd.DataFrame | None,
    balance_sheet: pd.DataFrame | None,
    cash_flow: pd.DataFrame | None = None,
    params: Mapping[str, Any],
) -> int | None:
    """Full Piotroski F-Score (0-9).

    Wraps ``durability._partial_fscore`` — the validated 7-signal core — and feeds it the
    latest full-fiscal-year CFO and net income so the 2 cash-flow signals (CFO>0 and the
    accrual check CFO>NI) fire, reaching the full 9 points. Without cash flow, the score is
    capped at the 7 non-cash signals (still returned, clearly < 9).

    Returns the integer raw count, or ``None`` when financial history is too thin to compute
    the minimum number of signals (``fscore_min_checks`` in the durability YAML block).
    """
    cfg = params.get("durability", {}) if isinstance(params, Mapping) else {}
    inc = _periodic_items(financials)
    bs = _periodic_items(balance_sheet)
    cfo_fy, ni_fy = _latest_fy_cfo_ni(cash_flow, inc)
    raw, _sub = _partial_fscore(inc, bs, cfg, cfo=cfo_fy, ni=ni_fy)
    return raw


# ── Shareholder Yield ─────────────────────────────────────────────────────────
def shareholder_yield(
    *,
    balance_sheet: pd.DataFrame | None,
    per: pd.DataFrame | None,
    market_cap: float | None,
    params: Mapping[str, Any],
) -> dict:
    """Shareholder yield = cash dividend yield + net buyback yield + net debt-reduction yield.

    - ``div``                — latest cash dividend yield from the ``per`` dataset
                               (``dividend_yield`` column, percent -> fraction).
    - ``net_buyback``        — YoY *decrease* in ``CapitalStock`` as a fraction of the prior
                               CapitalStock. If shares were ISSUED (CapitalStock rose), this is
                               flagged via ``diluted=True`` and contributes 0 (never subtracted),
                               per spec ("若增發則標記,不可扣除").
    - ``net_debt_reduction`` — YoY decrease in total interest-bearing debt
                               (long-term + short-term) divided by market cap. Can be negative
                               when debt rose (a genuine drag, not flagged).
    - ``total``              — sum of the three (missing terms omitted from the sum).

    Returns ``{div, net_buyback, net_debt_reduction, total, diluted, missing}``.
    """
    cfg = _value_cfg(params)
    back = _periods_back_index(cfg)
    bs = _periodic_items(balance_sheet)
    missing: list[str] = []

    # 1. Cash dividend yield (percent -> fraction).
    div = _latest_dividend_yield(per)
    if div is None:
        missing.append("dividend_yield")

    # 2. Net buyback = YoY CapitalStock reduction fraction (dilution flagged, never subtracted).
    cap_now = _bs_val(bs, 0, _CAPITAL_STOCK)
    cap_prev = _bs_val(bs, back, _CAPITAL_STOCK)
    net_buyback: float | None = None
    diluted = False
    if cap_now is not None and cap_prev not in (None, 0):
        change = (cap_prev - cap_now) / cap_prev   # >0 = shares reduced (buyback)
        if change >= 0:
            net_buyback = change
        else:
            diluted = True
            net_buyback = 0.0
    else:
        missing.append("capital_stock_yoy")

    # 3. Net debt reduction = YoY total-debt decrease / market cap.
    debt_now = _total_debt(bs, 0)
    debt_prev = _total_debt(bs, back)
    mc = _f(market_cap)
    net_debt_reduction: float | None = None
    if debt_now is not None and debt_prev is not None and mc is not None and mc > 0:
        net_debt_reduction = (debt_prev - debt_now) / mc
    else:
        missing.append("net_debt_reduction")

    parts = [v for v in (div, net_buyback, net_debt_reduction) if v is not None]
    total = sum(parts) if parts else None

    return {
        "div": div,
        "net_buyback": net_buyback,
        "net_debt_reduction": net_debt_reduction,
        "total": total,
        "diluted": diluted,
        "missing": missing,
    }


# ── helpers ─────────────────────────────────────────────────────────────────
def _latest_dividend_yield(per: pd.DataFrame | None) -> float | None:
    """Latest ``dividend_yield`` (percent) from the per dataset -> fraction. None if absent."""
    if per is None or per.empty or "dividend_yield" not in per.columns:
        return None
    series = per["dividend_yield"].dropna()
    if series.empty:
        return None
    val = _f(series.iloc[-1])
    if val is None:
        return None
    return val / 100.0


def _total_debt(bs: list[tuple[str, dict]], idx_back: int) -> float | None:
    """Sum of interest-bearing debt (long-term + short-term) at ``idx_back`` periods back.
    None only when NO debt line is present at that period."""
    parts = [_bs_val(bs, idx_back, k) for k in (*_LT_DEBT, *_ST_DEBT)]
    parts = [p for p in parts if p is not None]
    return sum(parts) if parts else None
