"""
Taiwan stock fundamental analysis: revenue, EPS, PE, ROE, margins, dividend, debt, cash flow.

Uses FinMind API for financial data when available.
Falls back to realistic mock data when API unavailable.
"""
import os
import httpx
from datetime import date, timedelta

FINMIND_BASE = "https://api.finmindtrade.com/api/v4/data"

# Mock financial data for common stocks
_MOCK_FUNDAMENTALS = {
    "2330": {
        "company_name": "台積電",
        "latest_revenue": "196.8B",
        "revenue_yoy": 29.3,
        "revenue_mom": 8.2,
        "eps_latest": 32.8,
        "eps_yoy": 85.5,
        "pe_ratio": 27.5,
        "pb_ratio": 7.2,
        "roe": 25.8,
        "roa": 18.5,
        "gross_margin": 54.2,
        "operating_margin": 38.5,
        "net_margin": 35.2,
        "dividend_yield": 2.1,
        "payout_ratio": 55.0,
        "debt_ratio": 18.5,
        "current_ratio": 2.8,
        "quick_ratio": 2.4,
        "operating_cf": "1.2T",
        "free_cf": "850B",
        "cf_trend": "strong",
    },
    "0050": {
        "company_name": "元大台灣50",
        "latest_revenue": "N/A",
        "revenue_yoy": 0,
        "revenue_mom": 0,
        "eps_latest": "N/A",
        "eps_yoy": 0,
        "pe_ratio": 18.5,
        "pb_ratio": 1.8,
        "roe": 15.2,
        "roa": 8.5,
        "gross_margin": 45.0,
        "operating_margin": 28.5,
        "net_margin": 22.0,
        "dividend_yield": 3.5,
        "payout_ratio": 65.0,
        "debt_ratio": 25.0,
        "current_ratio": 2.2,
        "quick_ratio": 2.0,
        "operating_cf": "N/A",
        "free_cf": "N/A",
        "cf_trend": "stable",
    },
    "2454": {
        "company_name": "聯發科",
        "latest_revenue": "78.5B",
        "revenue_yoy": -18.5,
        "revenue_mom": 2.1,
        "eps_latest": 12.5,
        "eps_yoy": -65.2,
        "pe_ratio": 32.4,
        "pb_ratio": 4.5,
        "roe": 12.8,
        "roa": 8.2,
        "gross_margin": 42.5,
        "operating_margin": 22.5,
        "net_margin": 18.5,
        "dividend_yield": 1.8,
        "payout_ratio": 45.0,
        "debt_ratio": 22.0,
        "current_ratio": 2.5,
        "quick_ratio": 2.3,
        "operating_cf": "450B",
        "free_cf": "380B",
        "cf_trend": "declining",
    },
}


def _mock_fundamentals(symbol: str) -> dict:
    """Generate realistic mock fundamental data for a Taiwan stock."""
    if symbol in _MOCK_FUNDAMENTALS:
        return _MOCK_FUNDAMENTALS[symbol].copy()

    # Generic mock for unknown symbols
    return {
        "company_name": symbol,
        "latest_revenue": "N/A",
        "revenue_yoy": 15.0,
        "revenue_mom": 3.5,
        "eps_latest": 10.0,
        "eps_yoy": 20.0,
        "pe_ratio": 20.0,
        "pb_ratio": 2.0,
        "roe": 15.0,
        "roa": 8.0,
        "gross_margin": 40.0,
        "operating_margin": 25.0,
        "net_margin": 20.0,
        "dividend_yield": 2.5,
        "payout_ratio": 50.0,
        "debt_ratio": 20.0,
        "current_ratio": 2.0,
        "quick_ratio": 1.8,
        "operating_cf": "N/A",
        "free_cf": "N/A",
        "cf_trend": "stable",
    }


async def _fetch(client: httpx.AsyncClient, dataset: str, symbol: str, start: str, token: str) -> list[dict]:
    try:
        resp = await client.get(
            FINMIND_BASE,
            params={"dataset": dataset, "data_id": symbol, "start_date": start, "token": token},
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("status") == 200:
            return payload.get("data", [])
    except Exception:
        pass
    return []


def _by_period(rows: list[dict]) -> dict[str, dict[str, float]]:
    """Group long-format (date/type/value) rows into {date: {type: value}}."""
    out: dict[str, dict[str, float]] = {}
    for row in rows:
        period = str(row.get("date") or "")[:10]
        type_code = str(row.get("type") or "")
        try:
            out.setdefault(period, {})[type_code] = float(row.get("value"))
        except (TypeError, ValueError):
            continue
    return out


def _pick(period: dict[str, float], *codes: str):
    for code in codes:
        if code in period and period[code] is not None:
            return period[code]
    return None


def _human_twd(value: float | None) -> str:
    if value is None:
        return "N/A"
    for unit, div in (("T", 1e12), ("B", 1e9), ("M", 1e6)):
        if abs(value) >= div:
            return f"{value / div:.1f}{unit}"
    return f"{value:,.0f}"


def _pct(numer: float | None, denom: float | None) -> float | None:
    if numer is None or not denom:
        return None
    return round(numer / denom * 100, 2)


async def get_tw_fundamentals(symbol: str) -> tuple[dict, bool]:
    """Fetch Taiwan stock fundamental metrics from FinMind (real datasets).

    Returns: (fundamentals_dict, is_mock). Datasets (all free-tier, long
    format date/type/value except month-revenue and PER):
      TaiwanStockMonthRevenue          -> revenue level / YoY / MoM
      TaiwanStockPER                   -> PER / PBR / dividend yield
      TaiwanStockFinancialStatements   -> EPS, margins (quarterly)
      TaiwanStockBalanceSheet          -> ROE/ROA denominators, debt/current ratios
      TaiwanStockCashFlowsStatement    -> operating / free cash flow + trend
    Missing individual fields degrade to None — never fabricated.
    """
    token = os.getenv("FINMIND_API_KEY") or os.getenv("FINMIND_TOKEN")
    if not token:
        return _mock_fundamentals(symbol), True

    today = date.today()
    start_14m = (today - timedelta(days=430)).isoformat()
    start_30d = (today - timedelta(days=30)).isoformat()
    start_30mo = (today - timedelta(days=920)).isoformat()  # ~5+ quarters for EPS YoY
    start_15mo = (today - timedelta(days=460)).isoformat()

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            import asyncio

            info_rows, rev_rows, per_rows, fin_rows, bs_rows, cf_rows = await asyncio.gather(
                _fetch(client, "TaiwanStockInfo", symbol, "", token),
                _fetch(client, "TaiwanStockMonthRevenue", symbol, start_14m, token),
                _fetch(client, "TaiwanStockPER", symbol, start_30d, token),
                _fetch(client, "TaiwanStockFinancialStatements", symbol, start_30mo, token),
                _fetch(client, "TaiwanStockBalanceSheet", symbol, start_15mo, token),
                _fetch(client, "TaiwanStockCashFlowsStatement", symbol, start_15mo, token),
            )
    except Exception:
        return _mock_fundamentals(symbol), True

    company_name = info_rows[0].get("stock_name", symbol) if info_rows else symbol

    # No usable statement/revenue data at all -> honest mock
    if not rev_rows and not fin_rows:
        return _mock_fundamentals(symbol), True

    # ── Revenue (monthly) ──
    latest_revenue = revenue_yoy = revenue_mom = None
    if rev_rows:
        rows = sorted(rev_rows, key=lambda r: r.get("date", ""))
        latest_rev = float(rows[-1].get("revenue", 0) or 0)
        latest_revenue = _human_twd(latest_rev)
        if len(rows) >= 2 and float(rows[-2].get("revenue", 0) or 0):
            revenue_mom = round((latest_rev / float(rows[-2]["revenue"]) - 1) * 100, 2)
        if len(rows) >= 13 and float(rows[-13].get("revenue", 0) or 0):
            revenue_yoy = round((latest_rev / float(rows[-13]["revenue"]) - 1) * 100, 2)

    # ── Valuation (daily PER table) ──
    pe_ratio = pb_ratio = dividend_yield = None
    if per_rows:
        latest = sorted(per_rows, key=lambda r: r.get("date", ""))[-1]
        pe_ratio = float(latest.get("PER") or 0) or None
        pb_ratio = float(latest.get("PBR") or 0) or None
        dividend_yield = float(latest.get("dividend_yield") or 0) or None

    # ── Income statement (quarterly, long format) ──
    eps_latest = eps_yoy = gross_margin = operating_margin = net_margin = None
    ttm_net_income = None
    fin_periods = _by_period(fin_rows)
    if fin_periods:
        dates = sorted(fin_periods)
        latest_q = fin_periods[dates[-1]]
        revenue_q = _pick(latest_q, "Revenue")
        eps_latest = _pick(latest_q, "EPS")
        gross_margin = _pct(_pick(latest_q, "GrossProfit"), revenue_q)
        operating_margin = _pct(_pick(latest_q, "OperatingIncome"), revenue_q)
        net_margin = _pct(
            _pick(latest_q, "IncomeAfterTaxes", "TotalConsolidatedProfitForThePeriod"), revenue_q
        )
        if len(dates) >= 5:
            prior_eps = _pick(fin_periods[dates[-5]], "EPS")
            if eps_latest is not None and prior_eps:
                eps_yoy = round((eps_latest / prior_eps - 1) * 100, 2)
        net_vals = [
            _pick(fin_periods[d], "IncomeAfterTaxes", "TotalConsolidatedProfitForThePeriod")
            for d in dates[-4:]
        ]
        if all(v is not None for v in net_vals) and len(net_vals) == 4:
            ttm_net_income = sum(net_vals)

    # ── Balance sheet (quarterly, long format) ──
    roe = roa = debt_ratio = current_ratio = quick_ratio = None
    bs_periods = _by_period(bs_rows)
    if bs_periods:
        latest_bs = bs_periods[sorted(bs_periods)[-1]]
        equity = _pick(latest_bs, "Equity", "TotalEquity", "EquityAttributableToOwnersOfParent")
        total_assets = _pick(latest_bs, "TotalAssets")
        liabilities = _pick(latest_bs, "Liabilities", "TotalLiabilities")
        current_assets = _pick(latest_bs, "CurrentAssets")
        current_liabilities = _pick(latest_bs, "CurrentLiabilities")
        inventories = _pick(latest_bs, "Inventories")
        roe = _pct(ttm_net_income, equity)
        roa = _pct(ttm_net_income, total_assets)
        debt_ratio = _pct(liabilities, total_assets)
        if current_assets is not None and current_liabilities:
            current_ratio = round(current_assets / current_liabilities, 2)
            if inventories is not None:
                quick_ratio = round((current_assets - inventories) / current_liabilities, 2)

    # ── Cash flow (quarterly, long format) ──
    operating_cf = free_cf = "N/A"
    cf_trend = "stable"
    cf_periods = _by_period(cf_rows)
    if cf_periods:
        cf_dates = sorted(cf_periods)
        latest_cf = cf_periods[cf_dates[-1]]
        op = _pick(latest_cf, "CashFlowsFromOperatingActivities", "NetCashInflowFromOperatingActivities")
        capex = _pick(latest_cf, "PropertyAndPlantAndEquipment")
        operating_cf = _human_twd(op)
        if op is not None and capex is not None:
            free_cf = _human_twd(op - abs(capex))
        if len(cf_dates) >= 2:
            prior_op = _pick(
                cf_periods[cf_dates[-2]],
                "CashFlowsFromOperatingActivities", "NetCashInflowFromOperatingActivities",
            )
            if op is not None and prior_op is not None:
                cf_trend = "strong" if op > prior_op else ("declining" if op < prior_op else "stable")

    fundamentals = {
        "company_name": company_name,
        "latest_revenue": latest_revenue or "N/A",
        "revenue_yoy": revenue_yoy,
        "revenue_mom": revenue_mom,
        "eps_latest": eps_latest,
        "eps_yoy": eps_yoy,
        "pe_ratio": pe_ratio,
        "pb_ratio": pb_ratio,
        "roe": roe,
        "roa": roa,
        "gross_margin": gross_margin,
        "operating_margin": operating_margin,
        "net_margin": net_margin,
        "dividend_yield": dividend_yield,
        "payout_ratio": None,
        "debt_ratio": debt_ratio,
        "current_ratio": current_ratio,
        "quick_ratio": quick_ratio,
        "operating_cf": operating_cf,
        "free_cf": free_cf,
        "cf_trend": cf_trend,
    }
    return fundamentals, False
