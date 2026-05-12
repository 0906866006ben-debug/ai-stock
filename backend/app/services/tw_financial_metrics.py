"""
Real financial metrics fetcher for Taiwan stocks.
Integrates P/E ratios, market cap, growth rates, and financial health metrics.
Provides 3-tier fallback: Real data → Yahoo Finance → Realistic mock.
"""

import os
import httpx
from datetime import datetime, timedelta


async def fetch_real_metrics(symbol: str) -> dict:
    """
    Fetch real financial metrics for Taiwan stock analysis.
    Returns 20+ metrics for valuation, growth, and financial health analysis.

    3-tier fallback:
    1. FinMind API (if key available)
    2. Yahoo Finance fallback (headlines only)
    3. Realistic mock data

    Returns dict with keys:
    - Market: current_price, market_cap, pe_ratio, pb_ratio, ps_ratio
    - Growth: revenue_yoy, revenue_qoq, eps_yoy, eps_latest
    - Margins: gross_margin, operating_margin, net_margin
    - Health: debt_ratio, current_ratio, roe, roa, fcf_margin
    - Performance: price_30d, ytd_performance
    - Valuation: forward_pe, ev_sales, peg_ratio
    - Dividend: dividend_yield, payout_ratio
    - Status: data_source, is_mock
    """

    # Try FinMind first (integrated with existing infrastructure)
    result = await _fetch_finmind_metrics(symbol)
    if result and result.get("status") == "success":
        return result

    # Fallback to Yahoo Finance
    result = await _fetch_yahoo_metrics(symbol)
    if result and result.get("status") == "success":
        return result

    # Final fallback: realistic mock
    return _generate_mock_metrics(symbol)


async def _fetch_finmind_metrics(symbol: str) -> dict:
    """Try to fetch from FinMind API (existing integration)."""
    try:
        # Check if we have FinMind key
        finmind_key = os.getenv("FINMIND_API_KEY")
        if not finmind_key:
            return None

        async with httpx.AsyncClient(timeout=10) as client:
            # Fetch Taiwan stock daily data
            response = await client.get(
                "https://api.finmindtrade.com/api/v4/data",
                params={
                    "dataset": "TaiwanStockInfo",
                    "data_id": symbol,
                    "token": finmind_key,
                },
            )

            if response.status_code == 200:
                data = response.json()
                if data.get("data"):
                    stock_info = data["data"][0] if isinstance(data["data"], list) else data["data"]

                    # Parse metrics from FinMind response
                    return {
                        "status": "success",
                        "source": "finmind",
                        # Market metrics
                        "current_price": float(stock_info.get("current_price", 0)) or None,
                        "market_cap": stock_info.get("market_cap"),  # Usually not in FinMind
                        "pe_ratio": float(stock_info.get("pe_ratio", 0)) or None,
                        "pb_ratio": float(stock_info.get("pb_ratio", 0)) or None,
                        "ps_ratio": float(stock_info.get("ps_ratio", 0)) or None,
                        # Growth metrics
                        "revenue_yoy": float(stock_info.get("revenue_yoy", 0)) or None,
                        "eps_yoy": float(stock_info.get("eps_yoy", 0)) or None,
                        "eps_latest": float(stock_info.get("eps", 0)) or None,
                        # Margins
                        "gross_margin": float(stock_info.get("gross_margin", 0)) or None,
                        "operating_margin": float(stock_info.get("operating_margin", 0)) or None,
                        "net_margin": float(stock_info.get("net_margin", 0)) or None,
                        # Financial health
                        "debt_ratio": float(stock_info.get("debt_ratio", 0)) or None,
                        "current_ratio": float(stock_info.get("current_ratio", 0)) or None,
                        "roe": float(stock_info.get("roe", 0)) or None,
                        "roa": float(stock_info.get("roa", 0)) or None,
                        # Dividend
                        "dividend_yield": float(stock_info.get("dividend_yield", 0)) or None,
                        "payout_ratio": float(stock_info.get("payout_ratio", 0)) or None,
                        # Performance
                        "price_30d": stock_info.get("price_30d"),
                        "ytd_performance": stock_info.get("ytd_performance"),
                        "is_mock": False,
                    }
    except Exception:
        return None


async def _fetch_yahoo_metrics(symbol: str) -> dict:
    """Fallback to Yahoo Finance for key metrics."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            # Try Yahoo Finance Taiwan endpoint
            response = await client.get(
                f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{symbol}.TW",
                params={"modules": "price,summaryDetail,financialData,defaultKeyStatistics"},
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                },
            )

            if response.status_code == 200:
                data = response.json()
                if data.get("quoteSummary", {}).get("result"):
                    result = data["quoteSummary"]["result"][0]
                    price_data = result.get("price", {})
                    summary = result.get("summaryDetail", {})
                    financial = result.get("financialData", {})
                    stats = result.get("defaultKeyStatistics", {})

                    return {
                        "status": "success",
                        "source": "yahoo_finance",
                        # Market metrics
                        "current_price": price_data.get("regularMarketPrice", {}).get("raw"),
                        "market_cap": price_data.get("marketCap", {}).get("raw"),
                        "pe_ratio": summary.get("trailingPE", {}).get("raw"),
                        "pb_ratio": summary.get("priceToBook", {}).get("raw"),
                        "ps_ratio": summary.get("priceToSalesTrailing12Months", {}).get("raw"),
                        # Growth metrics (limited from Yahoo)
                        "revenue_yoy": financial.get("revenueGrowth", {}).get("raw"),
                        "eps_yoy": None,  # Not directly available
                        "eps_latest": financial.get("trailingEps", {}).get("raw"),
                        # Margins
                        "gross_margin": financial.get("grossMargins", {}).get("raw"),
                        "operating_margin": financial.get("operatingMargins", {}).get("raw"),
                        "net_margin": financial.get("profitMargins", {}).get("raw"),
                        # Financial health
                        "debt_ratio": financial.get("debtToEquity", {}).get("raw"),
                        "current_ratio": financial.get("currentRatio", {}).get("raw"),
                        "roe": financial.get("returnOnEquity", {}).get("raw"),
                        "roa": financial.get("returnOnAssets", {}).get("raw"),
                        # Dividend
                        "dividend_yield": summary.get("trailingAnnualDividendYield", {}).get("raw"),
                        "payout_ratio": summary.get("payoutRatio", {}).get("raw"),
                        # Performance
                        "price_30d": price_data.get("regularMarketChangePercent", {}).get("raw"),
                        "ytd_performance": None,  # Need to calculate
                        "is_mock": False,
                    }
    except Exception:
        return None

    return None


def _generate_mock_metrics(symbol: str) -> dict:
    """
    Generate realistic mock metrics when APIs unavailable.
    Includes variance so not templated.
    """
    import random

    # Add realistic variance
    pe_base = 20 + random.uniform(-5, 10)
    pb_base = 2.5 + random.uniform(-1, 2)
    revenue_growth = random.uniform(5, 35)
    eps_growth = random.uniform(8, 50)

    return {
        "status": "success",
        "source": "mock",
        # Market metrics
        "current_price": 150 + random.uniform(-50, 100),
        "market_cap": 5_000_000_000_000 + random.uniform(-2e12, 3e12),  # TWD
        "pe_ratio": max(8, pe_base),
        "pb_ratio": max(1, pb_base),
        "ps_ratio": 4 + random.uniform(-1.5, 3),
        # Growth metrics
        "revenue_yoy": revenue_growth,
        "revenue_qoq": random.uniform(2, 12),
        "eps_yoy": eps_growth,
        "eps_latest": 30 + random.uniform(5, 50),
        # Margins
        "gross_margin": 35 + random.uniform(-10, 20),  # %
        "operating_margin": 20 + random.uniform(-8, 15),  # %
        "net_margin": 15 + random.uniform(-5, 20),  # %
        # Financial health
        "debt_ratio": 25 + random.uniform(-15, 20),  # %
        "current_ratio": 1.5 + random.uniform(-0.5, 1),
        "roe": 15 + random.uniform(-5, 20),  # %
        "roa": 8 + random.uniform(-3, 12),  # %
        "fcf_margin": 10 + random.uniform(-3, 10),  # %
        # Dividend
        "dividend_yield": 2 + random.uniform(-0.5, 3),  # %
        "payout_ratio": 30 + random.uniform(-10, 20),  # %
        # Performance
        "price_30d": random.uniform(-10, 20),  # %
        "ytd_performance": random.uniform(-15, 50),  # %
        # Comparison metrics
        "sector_avg_pe": 25 + random.uniform(-5, 10),
        "sector_avg_pb": 3 + random.uniform(-1, 2),
        "industry_pe": 28 + random.uniform(-8, 12),
        # Forward metrics (estimated)
        "forward_pe": pe_base * 0.85,  # Usually lower than trailing
        "ev_sales": 3 + random.uniform(-1, 3),
        "peg_ratio": max(0.5, (pe_base / eps_growth) * 100),
        # Status
        "is_mock": True,
    }


def format_metrics_for_narrative(metrics: dict) -> str:
    """Format metrics into readable narrative blocks for equity research agent."""
    if not metrics:
        return ""

    source = metrics.get("source", "unknown")
    is_mock = metrics.get("is_mock", False)

    source_note = f"(來源: {source}{'模擬' if is_mock else '實時'})" if source else ""

    return f"""
## 財務數據摘要 {source_note}

### 市場指標
- 股價: TWD {metrics.get('current_price', 'N/A'):.2f}
- 市值: TWD {metrics.get('market_cap', 0):,.0f}
- 30天漲幅: {metrics.get('price_30d', 'N/A'):.1f}%
- YTD漲幅: {metrics.get('ytd_performance', 'N/A'):.1f}%

### 估值指標
- 本益比 (Trailing P/E): {metrics.get('pe_ratio', 'N/A'):.1f}x
- 本淨比 (P/B): {metrics.get('pb_ratio', 'N/A'):.2f}x
- 本營比 (P/S): {metrics.get('ps_ratio', 'N/A'):.2f}x
- Forward P/E: {metrics.get('forward_pe', 'N/A'):.1f}x
- EV/Sales: {metrics.get('ev_sales', 'N/A'):.2f}x
- PEG比率: {metrics.get('peg_ratio', 'N/A'):.2f}

### 成長指標
- 營收YoY: {metrics.get('revenue_yoy', 'N/A'):.1f}%
- 營收QoQ: {metrics.get('revenue_qoq', 'N/A'):.1f}%
- EPS YoY: {metrics.get('eps_yoy', 'N/A'):.1f}%
- 最新EPS: {metrics.get('eps_latest', 'N/A'):.2f}元

### 利潤率趨勢
- 毛利率: {metrics.get('gross_margin', 'N/A'):.1f}%
- 營益率: {metrics.get('operating_margin', 'N/A'):.1f}%
- 淨利率: {metrics.get('net_margin', 'N/A'):.1f}%
- 自由現金流率: {metrics.get('fcf_margin', 'N/A'):.1f}%

### 財務健康度
- 負債比: {metrics.get('debt_ratio', 'N/A'):.1f}%
- 流動比: {metrics.get('current_ratio', 'N/A'):.2f}x
- ROE: {metrics.get('roe', 'N/A'):.1f}%
- ROA: {metrics.get('roa', 'N/A'):.1f}%

### 股利政策
- 配息殖利率: {metrics.get('dividend_yield', 'N/A'):.2f}%
- 配息率: {metrics.get('payout_ratio', 'N/A'):.1f}%

### 同業對標
- 產業均數P/E: {metrics.get('sector_avg_pe', 'N/A'):.1f}x
- 產業均數P/B: {metrics.get('sector_avg_pb', 'N/A'):.2f}x
"""
