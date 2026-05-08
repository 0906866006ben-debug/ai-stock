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


async def get_tw_fundamentals(symbol: str) -> tuple[dict, bool]:
    """
    Fetch Taiwan stock fundamental metrics.

    Returns: (fundamentals_dict, is_mock)

    fundamentals_dict keys:
      company_name, latest_revenue, revenue_yoy, revenue_mom,
      eps_latest, eps_yoy, pe_ratio, pb_ratio, roe, roa,
      gross_margin, operating_margin, net_margin,
      dividend_yield, payout_ratio, debt_ratio, current_ratio, quick_ratio,
      operating_cf, free_cf, cf_trend
    """
    token = os.getenv("FINMIND_API_KEY")
    if not token:
        return _mock_fundamentals(symbol), True

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Fetch company info first to get company name
            resp_info = await client.get(
                FINMIND_BASE,
                params={
                    "dataset": "TaiwanStockInfo",
                    "data_id": symbol,
                    "token": token,
                },
            )
            resp_info.raise_for_status()
            info_data = resp_info.json()

            if info_data.get("status") != 200 or not info_data.get("data"):
                return _mock_fundamentals(symbol), True

            company_name = info_data["data"][0].get("stock_name", symbol)

            # Fetch financial metrics
            resp_fin = await client.get(
                FINMIND_BASE,
                params={
                    "dataset": "TaiwanStockFinancials",
                    "data_id": symbol,
                    "token": token,
                },
            )
            resp_fin.raise_for_status()
            fin_data = resp_fin.json()

            if fin_data.get("status") != 200 or not fin_data.get("data"):
                return _mock_fundamentals(symbol), True

            # Parse financial data (latest)
            financials = fin_data.get("data", [])
            if not financials:
                return _mock_fundamentals(symbol), True

            latest = financials[-1] if isinstance(financials, list) else financials

            # Extract metrics (exact field names depend on FinMind response)
            fundamentals = {
                "company_name": company_name,
                "latest_revenue": latest.get("revenue", "N/A"),
                "revenue_yoy": float(latest.get("revenue_yoy", 0)) if latest.get("revenue_yoy") else 0,
                "revenue_mom": float(latest.get("revenue_mom", 0)) if latest.get("revenue_mom") else 0,
                "eps_latest": float(latest.get("eps", 0)) if latest.get("eps") else 0,
                "eps_yoy": float(latest.get("eps_yoy", 0)) if latest.get("eps_yoy") else 0,
                "pe_ratio": float(latest.get("pe_ratio", 0)) if latest.get("pe_ratio") else 0,
                "pb_ratio": float(latest.get("pb_ratio", 0)) if latest.get("pb_ratio") else 0,
                "roe": float(latest.get("roe", 0)) if latest.get("roe") else 0,
                "roa": float(latest.get("roa", 0)) if latest.get("roa") else 0,
                "gross_margin": float(latest.get("gross_margin", 0)) if latest.get("gross_margin") else 0,
                "operating_margin": float(latest.get("operating_margin", 0)) if latest.get("operating_margin") else 0,
                "net_margin": float(latest.get("net_margin", 0)) if latest.get("net_margin") else 0,
                "dividend_yield": float(latest.get("dividend_yield", 0)) if latest.get("dividend_yield") else 0,
                "payout_ratio": float(latest.get("payout_ratio", 0)) if latest.get("payout_ratio") else 0,
                "debt_ratio": float(latest.get("debt_ratio", 0)) if latest.get("debt_ratio") else 0,
                "current_ratio": float(latest.get("current_ratio", 0)) if latest.get("current_ratio") else 0,
                "quick_ratio": float(latest.get("quick_ratio", 0)) if latest.get("quick_ratio") else 0,
                "operating_cf": latest.get("operating_cf", "N/A"),
                "free_cf": latest.get("free_cf", "N/A"),
                "cf_trend": latest.get("cf_trend", "stable"),
            }

            return fundamentals, False

    except Exception:
        return _mock_fundamentals(symbol), True
