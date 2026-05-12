import asyncio
from datetime import date

from .fmp_client import fmp_get


def _fmt_large(val: float | None) -> str | None:
    if val is None:
        return None
    val = float(val)
    if abs(val) >= 1e12:
        return f"${val / 1e12:.2f}T"
    if abs(val) >= 1e9:
        return f"${val / 1e9:.2f}B"
    if abs(val) >= 1e6:
        return f"${val / 1e6:.2f}M"
    return f"${val:,.0f}"


def _fmt_pct(val: float | None) -> str | None:
    if val is None:
        return None
    return f"{float(val) * 100:.1f}%"


def _fmt_num(val: float | None, decimals: int = 1) -> str | None:
    if val is None:
        return None
    return f"{float(val):.{decimals}f}"


async def get_fmp_fundamentals(symbol: str) -> dict:
    """Fetch comprehensive fundamental data from FMP for investment analysis."""
    income_coro = fmp_get("income-statement", {"symbol": symbol, "limit": 4})
    cf_coro = fmp_get("cash-flow-statement", {"symbol": symbol, "limit": 1})
    metrics_coro = fmp_get("key-metrics", {"symbol": symbol, "limit": 1})
    ratios_coro = fmp_get("ratios", {"symbol": symbol, "limit": 1})
    target_coro = fmp_get("price-target-consensus", {"symbol": symbol})
    # earnings: do NOT pass limit — it breaks the endpoint
    earnings_coro = fmp_get("earnings", {"symbol": symbol})
    esg_coro = fmp_get("esg-disclosures", {"symbol": symbol, "limit": 1})

    results = await asyncio.gather(
        income_coro, cf_coro, metrics_coro, ratios_coro,
        target_coro, earnings_coro, esg_coro,
        return_exceptions=True,
    )
    income_data, cf_data, metrics_data, ratios_data, target_data, earnings_data, esg_data = results

    financial_metrics: dict[str, str] = {}

    # Income statement — most recent period
    if isinstance(income_data, list) and income_data:
        latest = income_data[0]
        if rev := latest.get("revenue"):
            financial_metrics["revenue"] = _fmt_large(float(rev)) or ""
        if ni := latest.get("netIncome"):
            financial_metrics["net_income"] = _fmt_large(float(ni)) or ""
        if gp := latest.get("grossProfit"):
            financial_metrics["gross_profit"] = _fmt_large(float(gp)) or ""

    # Cash flow — free cash flow
    if isinstance(cf_data, list) and cf_data:
        cf = cf_data[0]
        fcf = cf.get("freeCashFlow")
        if fcf is None:
            ocf = cf.get("operatingCashFlow")
            capex = cf.get("capitalExpenditure")
            if ocf is not None and capex is not None:
                fcf = float(ocf) + float(capex)
        if fcf is not None:
            financial_metrics["free_cash_flow"] = _fmt_large(float(fcf)) or ""

    # Key metrics — includes ROE, ROA, EV, market cap
    if isinstance(metrics_data, list) and metrics_data:
        m = metrics_data[0]
        if mc := m.get("marketCap"):
            financial_metrics["market_cap"] = _fmt_large(float(mc)) or ""
        if ev := m.get("enterpriseValue"):
            financial_metrics["enterprise_value"] = _fmt_large(float(ev)) or ""
        if ev_eb := m.get("evToEBITDA"):
            financial_metrics["ev_ebitda"] = f"{float(ev_eb):.1f}x"
        if cr := m.get("currentRatio"):
            financial_metrics["current_ratio"] = f"{float(cr):.2f}"
        # ROE and ROA live in key-metrics, not ratios
        if roe := m.get("returnOnEquity"):
            financial_metrics["roe"] = _fmt_pct(float(roe)) or ""
        if roa := m.get("returnOnAssets"):
            financial_metrics["roa"] = _fmt_pct(float(roa)) or ""

    # Ratios — margins and valuation multiples
    if isinstance(ratios_data, list) and ratios_data:
        r = ratios_data[0]
        for src_key, dst_key in [
            ("grossProfitMargin", "gross_margin"),
            ("operatingProfitMargin", "operating_margin"),
            ("netProfitMargin", "net_margin"),
        ]:
            if v := r.get(src_key):
                financial_metrics[dst_key] = _fmt_pct(float(v)) or ""
        # Correct FMP stable API field names
        if v := r.get("priceToEarningsRatio"):
            financial_metrics["pe_ratio"] = _fmt_num(float(v)) or ""
        if v := r.get("priceToBookRatio"):
            financial_metrics["pb_ratio"] = _fmt_num(float(v), 2) or ""
        if v := r.get("debtToEquityRatio") or r.get("debtEquityRatio"):
            financial_metrics["debt_equity"] = _fmt_num(float(v), 2) or ""

    # Analyst price targets
    analyst: dict[str, str] = {}
    raw_target = target_data
    if isinstance(raw_target, list) and raw_target:
        raw_target = raw_target[0]
    if isinstance(raw_target, dict) and raw_target.get("targetConsensus"):
        analyst["consensus"] = f"${float(raw_target['targetConsensus']):.2f}"
        if h := raw_target.get("targetHigh"):
            analyst["high"] = f"${float(h):.2f}"
        if l := raw_target.get("targetLow"):
            analyst["low"] = f"${float(l):.2f}"
        if med := raw_target.get("targetMedian"):
            analyst["median"] = f"${float(med):.2f}"

    # Earnings — next date + last actuals (no limit param allowed)
    next_earnings_date: str | None = None
    last_earnings: dict = {}
    if isinstance(earnings_data, list) and earnings_data:
        today_str = date.today().isoformat()
        future = [e for e in earnings_data if (e.get("date") or "") >= today_str and e.get("epsActual") is None]
        past = [e for e in earnings_data if (e.get("date") or "") < today_str and e.get("epsActual") is not None]
        if future:
            next_earnings_date = future[0].get("date")
        if past:
            le = past[0]
            last_earnings = {
                "date": le.get("date"),
                "eps_actual": le.get("epsActual"),
                "eps_estimated": le.get("epsEstimated"),
            }

    # ESG scores
    esg: dict = {}
    if isinstance(esg_data, list) and esg_data:
        e = esg_data[0]
        esg = {
            "environmental": e.get("environmentalScore"),
            "social": e.get("socialScore"),
            "governance": e.get("governanceScore"),
            "total": e.get("ESGScore"),
        }

    return {
        "financial_metrics": financial_metrics,
        "analyst": analyst,
        "next_earnings_date": next_earnings_date,
        "last_earnings": last_earnings,
        "esg": esg,
    }
