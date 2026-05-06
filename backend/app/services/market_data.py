import yfinance as yf

MOCK_MARKET = {
    "company_name": "Demo Company Inc.",
    "current_price": 150.00,
    "price_change_percent": 0.85,
    "chart_data": [
        {"time": f"2025-{m:02d}-01", "value": round(140.0 + i * 2.5, 2)}
        for i, m in enumerate(range(11, 17))
    ],
}


async def get_market_data(symbol: str) -> dict:
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="6mo")
        if hist.empty:
            return MOCK_MARKET

        info = ticker.info or {}
        company_name = info.get("longName") or info.get("shortName") or symbol
        current_price = float(info.get("currentPrice") or info.get("regularMarketPrice") or 0.0)
        change_pct = float(info.get("regularMarketChangePercent") or 0.0)

        chart_data = []
        for date, close in hist["Close"].items():
            try:
                chart_data.append({
                    "time": date.strftime("%Y-%m-%d"),
                    "value": round(float(close), 2),
                })
            except Exception:
                continue

        if not current_price and chart_data:
            current_price = chart_data[-1]["value"]

        return {
            "company_name": company_name,
            "current_price": current_price,
            "price_change_percent": change_pct,
            "chart_data": sorted(chart_data, key=lambda p: p["time"]),
        }
    except Exception:
        return MOCK_MARKET
