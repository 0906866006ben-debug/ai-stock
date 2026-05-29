"""Live FinMind fundamentals adapter (call-and-decode, no backfill needed).

Fetches the fundamental datasets on demand via the loop-free `query_finmind`
proxy, reshapes FinMind's long (`type`/`value`) format into the same DataFrame
contract the PIT store produces, and reuses `pit_inputs.assemble_pit_inputs` so
the decode is identical to the backfilled path. Result is cached per
(symbol, as-of-day) so a repeat screen does not re-hit FinMind.

This lets the screener evaluate stocks that are NOT in the local PIT store
(e.g. financials / traditional / shipping) without running the heavy backfill.
Intended for live "as of today" screening; it is not a point-in-time-perfect
source for historical backtests (filing dates are approximated as period_end+45d).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from backend.app.services import file_cache
from backend.app.services.finmind_query import query_finmind
from backend.app.services.strategy.canslim.pit_inputs import assemble_pit_inputs

_CACHE_NAMESPACE = "live_finmind_inputs"
_FILING_LAG_DAYS = 45  # TW quarterly filing deadline ≈ period_end + 45 days


def _shift(as_of_date: str, days: int) -> str:
    base = datetime.strptime(str(as_of_date)[:10], "%Y-%m-%d")
    return (base - timedelta(days=days)).strftime("%Y-%m-%d")


async def build_live_inputs(symbol: str, as_of_date: str) -> tuple[dict, dict, str | None]:
    """Return (detail, fin_metrics, eps_filing_date) from live FinMind calls.

    Returns ({}, {}, None) when nothing usable comes back (e.g. rate-limited),
    and only caches when real fundamental data was retrieved."""
    key = f"{symbol}_{str(as_of_date)[:10]}"
    cached = file_cache.load(_CACHE_NAMESPACE, key)
    if isinstance(cached, dict) and cached.get("fin_metrics") is not None:
        return cached.get("detail") or {}, cached.get("fin_metrics") or {}, cached.get("eps_filing_date")

    end = str(as_of_date)[:10]
    revenue_rows = (await query_finmind("TaiwanStockMonthRevenue", data_id=symbol, start_date=_shift(end, 1100), end_date=end)).get("rows") or []
    inst_rows = (await query_finmind("TaiwanStockInstitutionalInvestorsBuySell", data_id=symbol, start_date=_shift(end, 45), end_date=end)).get("rows") or []
    fin_rows = (await query_finmind("TaiwanStockFinancialStatements", data_id=symbol, start_date=_shift(end, 1900), end_date=end)).get("rows") or []
    bs_rows = (await query_finmind("TaiwanStockBalanceSheet", data_id=symbol, start_date=_shift(end, 1900), end_date=end)).get("rows") or []
    per_rows = (await query_finmind("TaiwanStockPER", data_id=symbol, start_date=_shift(end, 14), end_date=end)).get("rows") or []

    detail, fin_metrics, eps_filing_date = assemble_pit_inputs(
        _revenue_df(revenue_rows),
        _institutional_df(inst_rows),
        _financials_df(fin_rows),
        _balance_df(bs_rows),
        _per_df(per_rows),
    )

    if fin_rows or revenue_rows:  # got real data → safe to cache for the day
        file_cache.save(_CACHE_NAMESPACE, key, {"detail": detail, "fin_metrics": fin_metrics, "eps_filing_date": eps_filing_date})
    return detail, fin_metrics, eps_filing_date


def _revenue_df(rows: list[dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["date", "revenue"])
    return pd.DataFrame([{"date": r.get("date"), "revenue": r.get("revenue")} for r in rows])


def _institutional_df(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Pivot FinMind long rows (one per investor type) into net columns per date."""
    if not rows:
        return pd.DataFrame(columns=["date", "foreign_net", "trust_net", "dealer_net"])
    by_date: dict[str, dict[str, float]] = {}
    for r in rows:
        date = str(r.get("date"))
        name = str(r.get("name") or "")
        try:
            net = float(r.get("buy") or 0) - float(r.get("sell") or 0)
        except (TypeError, ValueError):
            continue
        bucket = by_date.setdefault(date, {"foreign_net": 0.0, "trust_net": 0.0, "dealer_net": 0.0})
        if "Trust" in name:
            bucket["trust_net"] += net
        elif "Foreign" in name:
            bucket["foreign_net"] += net
        elif "Dealer" in name:
            bucket["dealer_net"] += net
    out = [{"date": d, **vals} for d, vals in sorted(by_date.items())]
    return pd.DataFrame(out)


def _group_long_by_period(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    periods: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        date = str(r.get("date"))
        periods.setdefault(date, []).append({"type": r.get("type"), "value": r.get("value")})
    return periods


def _financials_df(rows: list[dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["period_end", "eps", "filing_date", "raw_json", "roe", "gross_margin", "operating_margin", "net_margin"])
    periods = _group_long_by_period(rows)
    out = []
    for period_end in sorted(periods):
        items = periods[period_end]
        eps = next((it["value"] for it in items if str(it.get("type")) == "EPS"), None)
        filing = (datetime.strptime(period_end[:10], "%Y-%m-%d") + timedelta(days=_FILING_LAG_DAYS)).strftime("%Y-%m-%d")
        out.append({
            "period_end": period_end,
            "eps": eps,
            "filing_date": filing,
            "raw_json": json.dumps(items, ensure_ascii=False),
            "roe": None,
            "gross_margin": None,
            "operating_margin": None,
            "net_margin": None,
        })
    return pd.DataFrame(out)


def _balance_df(rows: list[dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["period_end", "equity_parent", "equity", "raw_json"])
    periods = _group_long_by_period(rows)
    out = []
    for period_end in sorted(periods):
        items = periods[period_end]
        equity_parent = next((it["value"] for it in items if str(it.get("type")) == "EquityAttributableToOwnersOfParent"), None)
        equity = next((it["value"] for it in items if str(it.get("type")) == "Equity"), None)
        out.append({
            "period_end": period_end,
            "equity_parent": equity_parent,
            "equity": equity,
            "raw_json": json.dumps(items, ensure_ascii=False),
        })
    return pd.DataFrame(out)


def _per_df(rows: list[dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["per"])
    ordered = sorted(rows, key=lambda r: str(r.get("date")))
    return pd.DataFrame([{"per": r.get("PER")} for r in ordered])
