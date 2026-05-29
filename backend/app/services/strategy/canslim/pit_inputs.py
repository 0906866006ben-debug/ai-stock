"""Point-in-time CAN SLIM input adapter.

The adapter emits the exact `detail` and `fin_metrics` shapes already consumed
by build_features()/observe(). It does not change any CAN SLIM rule behavior.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from typing import Any

import pandas as pd

from backend.app.services.backtest.pit_fundamentals_store import PitFundamentalsStore


def build_pit_inputs(symbol: str, as_of_date: str, pit_store: PitFundamentalsStore) -> tuple[dict, dict, str | None]:
    """Return (detail, fin_metrics, eps_filing_date) in observe-compatible shapes."""
    revenue = pit_store.get_month_revenue_as_of(symbol, as_of_date, limit=36)
    institutional = pit_store.get_institutional_as_of(symbol, as_of_date, limit=20)
    financials = pit_store.get_financials_as_of(symbol, as_of_date, limit=20)
    balance_sheet = pit_store.get_balance_sheet_as_of(symbol, as_of_date, limit=8)
    per = pit_store.get_per_as_of(symbol, as_of_date, limit=1)
    return assemble_pit_inputs(revenue, institutional, financials, balance_sheet, per)


def assemble_pit_inputs(
    revenue: pd.DataFrame,
    institutional: pd.DataFrame,
    financials: pd.DataFrame,
    balance_sheet: pd.DataFrame,
    per: pd.DataFrame,
) -> tuple[dict, dict, str | None]:
    """Assemble observe-compatible (detail, fin_metrics, eps_filing_date) from
    already-loaded DataFrames. Shared by the PIT-store path and the live-FinMind
    path so both decode identically. Required columns:
      revenue: date, revenue
      institutional: date, foreign_net, trust_net, dealer_net
      financials: period_end, eps, filing_date, raw_json (+ optional margin/roe cols)
      balance_sheet: period_end, equity_parent/equity, raw_json
      per: per
    """
    detail: dict[str, Any] = {}
    month_revenue_yoy = _month_revenue_yoy(revenue)
    if month_revenue_yoy:
        detail["month_revenue_yoy"] = month_revenue_yoy
    if not institutional.empty:
        detail["foreign_net_5"] = _dated_net_series(institutional, "foreign_net")
        detail["trust_net_5"] = _dated_net_series(institutional, "trust_net")
        detail["dealer_net_5"] = _dated_net_series(institutional, "dealer_net")

    fin_metrics: dict[str, Any] = {}
    if not financials.empty:
        latest = financials.iloc[-1]
        fin_metrics["quarterly_eps_yoy"] = _quarterly_eps_yoy(financials)
        yoy_series = _quarterly_eps_yoy_series(financials)
        if yoy_series:
            fin_metrics["quarterly_eps_yoy_series"] = yoy_series
        annual_eps = _annual_eps_last3(financials)
        fin_metrics["annual_eps"] = annual_eps
        ttm_eps = _ttm_eps(financials)
        if ttm_eps is not None:
            fin_metrics["ttm_eps"] = ttm_eps
        if annual_eps:
            fin_metrics["latest_fy_eps"] = annual_eps[-1]
        stored_roe = _clean_float(latest.get("roe"))
        fin_metrics["roe"] = stored_roe if stored_roe is not None else _roe_ttm(financials, balance_sheet)
        margins = _margins_by_period(financials)
        op_series = [margins[p]["op"] for p in sorted(margins) if margins[p].get("op") is not None]
        if op_series:
            fin_metrics["op_margin_last4"] = op_series[-4:]
        latest_margin = margins.get(str(latest.get("period_end"))[:10], {})
        if latest_margin.get("gross") is not None:
            fin_metrics["gross_margin"] = latest_margin["gross"]
        if latest_margin.get("net") is not None:
            fin_metrics["net_margin"] = latest_margin["net"]
        eps_filing_date = str(latest.get("filing_date"))[:10] if latest.get("filing_date") else None
    else:
        eps_filing_date = None

    if not per.empty:
        fin_metrics["pe_ttm"] = _clean_float(per.iloc[-1].get("per"))

    shares = _shares_outstanding(balance_sheet)
    if shares is not None:
        fin_metrics["shares_outstanding"] = shares

    return detail, fin_metrics, eps_filing_date


def universe_shares_as_of(pit_store, universe, as_of_date: str) -> dict[str, float]:
    """Map symbol -> approximate shares outstanding as of `as_of_date`, PIT-safe, for
    the cross-sectional float-size percentile in screen_S. Symbols without share-capital
    data are omitted (no fabrication)."""
    out: dict[str, float] = {}
    for symbol in universe:
        try:
            bs = pit_store.get_balance_sheet_as_of(str(symbol), as_of_date, limit=1)
        except Exception:
            continue
        shares = _shares_outstanding(bs)
        if shares is not None:
            out[str(symbol)] = shares
    return out


def _shares_outstanding(balance_sheet: pd.DataFrame) -> float | None:
    """Approximate common shares outstanding from the latest balance sheet's share
    capital (股本). FinMind ships `CapitalStock` (TWD); TW par value is conventionally
    NT$10, so shares ≈ CapitalStock / 10. Approximate (some post-2014 issues use a
    flexible par), but adequate for a CROSS-SECTIONAL float-size percentile where only
    the relative ranking matters. Returns None when share capital is unavailable.

    VERIFIED (2026-05-28) more robust than the par-independent net_income/EPS: the
    latter breaks on minority-interest companies (1101: IncomeAfterTaxes is TOTAL not
    parent → total/EPS over-counts; (ni−nci)/EPS goes negative because FinMind's NCI
    line is comprehensive-income with messy sign). CapitalStock/10 stays the choice."""
    if balance_sheet is None or balance_sheet.empty:
        return None
    latest = balance_sheet.sort_values("period_end").iloc[-1]
    items = _raw_line_items(latest.get("raw_json"))
    capital = items.get("CapitalStock") or items.get("OrdinaryShare")
    if capital is None or capital <= 0:
        return None
    return float(capital) / 10.0


def _month_revenue_yoy(revenue: pd.DataFrame) -> list[float]:
    # FinMind monthly revenue has NO YoY field (it only ships raw `revenue` plus
    # revenue_year/revenue_month). The stored `revenue_yoy` column is unreliable
    # (it was populated from the year integer), so it is intentionally ignored and
    # YoY is computed from the revenue series: current month vs same calendar
    # month one year earlier.
    if revenue.empty:
        return []
    rows = revenue.sort_values("date").reset_index(drop=True)
    # Key the prior-year lookup by (year, month), NOT the full date string. The stored
    # `date` day-of-month can drift year to year (or be an announcement date), so an
    # exact-string match silently dropped months. (year, month) aligns the same
    # calendar month across years and avoids any leap-day date arithmetic crash.
    by_month: dict[tuple[int, int], float] = {}
    for _, row in rows.iterrows():
        ym = _year_month(str(row["date"]))
        rev = _clean_float(row.get("revenue"))
        if ym is not None and rev is not None:
            by_month[ym] = rev
    out: list[float] = []
    for _, row in rows.iterrows():
        ym = _year_month(str(row["date"]))
        current = _clean_float(row.get("revenue"))
        if ym is None or current is None:
            continue
        prior = by_month.get((ym[0] - 1, ym[1]))
        if prior and prior > 0:
            out.append((current - prior) / prior)
    return out


def _dated_net_series(frame: pd.DataFrame, column: str) -> list[dict[str, float | str]]:
    values = []
    for _, row in frame.sort_values("date").iterrows():
        net = _clean_float(row.get(column))
        if net is not None:
            values.append({"date": str(row["date"])[:10], "net": net})
    return values


def _quarterly_eps_yoy(financials: pd.DataFrame) -> float | None:
    rows = financials.dropna(subset=["eps"]).sort_values("period_end").reset_index(drop=True)
    if rows.empty:
        return None
    latest = rows.iloc[-1]
    latest_period = str(latest["period_end"])[:10]
    prior_period = _same_quarter_prior_year(latest_period)
    prior = rows[rows["period_end"].astype(str).str[:10] == prior_period]
    latest_eps = _clean_float(latest.get("eps"))
    prior_eps = _clean_float(prior.iloc[-1].get("eps")) if not prior.empty else None
    # Guard turnaround-from-loss: when the prior-year quarter was a loss (<= 0) a
    # YoY % is meaningless and would explode into a fake huge growth that trivially
    # passes the C screen. Return None so C falls back to other evidence honestly.
    if latest_eps is None or prior_eps is None or prior_eps <= 0:
        return None
    return (latest_eps - prior_eps) / prior_eps


def _quarterly_eps_yoy_series(financials: pd.DataFrame, max_quarters: int = 4) -> list[float]:
    """YoY growth for each of the last `max_quarters` quarters, oldest->newest, as
    fractions. Used to detect earnings ACCELERATION (O'Neil C). A quarter is skipped
    (not fabricated) when its prior-year quarter is missing or was a loss (<=0, where a
    YoY % is meaningless). Same single-quarter EPS convention as `_quarterly_eps_yoy`."""
    rows = financials.dropna(subset=["eps"]).sort_values("period_end").reset_index(drop=True)
    if rows.empty:
        return []
    by_period: dict[str, float] = {}
    for _, row in rows.iterrows():
        eps = _clean_float(row.get("eps"))
        if eps is not None:
            by_period[str(row["period_end"])[:10]] = eps
    # Walk backward from the latest quarter and keep a CONTIGUOUS run of computable
    # YoY values, stopping at the first quarter whose YoY can't be computed (missing or
    # loss-base prior year). This guarantees the returned series is consecutive quarters
    # so acceleration compares truly adjacent quarters, never across a skipped one.
    run: list[float] = []
    for period in sorted(by_period, reverse=True):
        prior = by_period.get(_same_quarter_prior_year(period))
        current = by_period.get(period)
        if current is not None and prior is not None and prior > 0:
            run.append((current - prior) / prior)
            if len(run) >= max_quarters:
                break
        else:
            break
    return list(reversed(run))


def _annual_eps_last3(financials: pd.DataFrame) -> list[float]:
    rows = financials.dropna(subset=["eps"]).copy()
    if rows.empty:
        return []
    rows["fiscal_year"] = rows["period_end"].astype(str).str[:4].astype(int)
    totals: dict[int, float] = defaultdict(float)
    counts: dict[int, int] = defaultdict(int)
    for _, row in rows.iterrows():
        eps = _clean_float(row.get("eps"))
        if eps is None:
            continue
        year = int(row["fiscal_year"])
        totals[year] += eps
        counts[year] += 1
    complete_years = [year for year in sorted(totals) if counts[year] >= 4]
    return [float(totals[year]) for year in complete_years[-3:]]


def _ttm_eps(financials: pd.DataFrame) -> float | None:
    """Sum of the last 4 quarterly EPS (trailing twelve months).

    Uses the same single-quarter EPS convention as `_annual_eps_last3`. Returns
    None when fewer than 4 quarters of EPS are available, so the A-pillar trend
    guard simply does not apply rather than comparing a partial window.
    """
    rows = financials.dropna(subset=["eps"]).sort_values("period_end")
    eps_values = [_clean_float(value) for value in rows["eps"].tolist()]
    eps_values = [value for value in eps_values if value is not None]
    if len(eps_values) < 4:
        return None
    return float(sum(eps_values[-4:]))


def _roe_ttm(financials: pd.DataFrame, balance_sheet: pd.DataFrame) -> float | None:
    """ROE = trailing-4-quarter net income / shareholders' equity.

    Net income (single-quarter IncomeAfterTaxes) comes from the income-statement
    line items; equity comes from the balance-sheet store (equity attributable to
    parent preferred, else total equity). Returns None when either input is
    unavailable, so screen_A can honestly fall back to the margin proxy.

    Convention: uses LATEST period-end equity (not the period-average ((begin+end)/2)).
    O'Neil/IBD do not mandate average equity; latest-equity is a common, stable
    simplification and changing it would shift the validated A/G-4 path, so it is kept
    deliberately rather than "corrected".
    """
    if financials.empty or balance_sheet.empty:
        return None
    net_income: list[float] = []
    for _, row in financials.sort_values("period_end").iterrows():
        value = _raw_line_items(row.get("raw_json")).get("IncomeAfterTaxes")
        if value is not None:
            net_income.append(value)
    if len(net_income) < 4:
        return None
    ttm_net_income = sum(net_income[-4:])

    latest_bs = balance_sheet.sort_values("period_end").iloc[-1]
    equity = _clean_float(latest_bs.get("equity_parent"))
    if equity is None:
        equity = _clean_float(latest_bs.get("equity"))
    if equity is None:
        bs_items = _raw_line_items(latest_bs.get("raw_json"))
        equity = bs_items.get("EquityAttributableToOwnersOfParent") or bs_items.get("Equity")
    if not equity or equity <= 0:
        return None
    return ttm_net_income / equity


def _margins_by_period(financials: pd.DataFrame) -> dict[str, dict[str, float | None]]:
    """Compute gross/operating/net margins per period from FinMind income-statement
    line items stored in `raw_json` (Revenue, GrossProfit, OperatingIncome,
    IncomeAfterTaxes). FinMind does not provide ready-made margin fields, so they
    must be derived. Falls back to stored margin columns when populated."""
    out: dict[str, dict[str, float | None]] = {}
    if financials.empty:
        return out
    for _, row in financials.iterrows():
        period = str(row.get("period_end"))[:10]
        items = _raw_line_items(row.get("raw_json"))
        revenue = items.get("Revenue")
        gross = op = net = None
        if revenue and revenue != 0:
            if items.get("GrossProfit") is not None:
                gross = items["GrossProfit"] / revenue
            if items.get("OperatingIncome") is not None:
                op = items["OperatingIncome"] / revenue
            if items.get("IncomeAfterTaxes") is not None:
                net = items["IncomeAfterTaxes"] / revenue
        out[period] = {
            "gross": _clean_float(row.get("gross_margin")) if _clean_float(row.get("gross_margin")) is not None else gross,
            "op": _clean_float(row.get("operating_margin")) if _clean_float(row.get("operating_margin")) is not None else op,
            "net": _clean_float(row.get("net_margin")) if _clean_float(row.get("net_margin")) is not None else net,
        }
    return out


def _raw_line_items(raw_json: Any) -> dict[str, float]:
    try:
        data = json.loads(raw_json) if raw_json else []
    except (TypeError, ValueError):
        return {}
    out: dict[str, float] = {}
    for item in data or []:
        if not isinstance(item, dict):
            continue
        type_code = item.get("type")
        value = _clean_float(item.get("value"))
        if type_code and value is not None and type_code not in out:
            out[str(type_code)] = value
    return out


def _year_month(date_value: str) -> tuple[int, int] | None:
    """(year, month) from a YYYY-MM-... date string, or None if unparseable."""
    try:
        return int(date_value[:4]), int(date_value[5:7])
    except (TypeError, ValueError):
        return None


def _same_quarter_prior_year(date_value: str) -> str:
    parsed = datetime.strptime(date_value[:10], "%Y-%m-%d")
    return parsed.replace(year=parsed.year - 1).strftime("%Y-%m-%d")


def _normalize_ratio(value: float | None) -> float | None:
    if value is None:
        return None
    if abs(value) > 1:
        return value / 100.0
    return value


def _clean_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(number):
        return None
    return number
