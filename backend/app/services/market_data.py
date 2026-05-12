import yfinance as yf

MOCK_MARKET = {
    "company_name": "Demo Company Inc.",
    "current_price": 150.00,
    "price_change_percent": 0.85,
    "chart_data": [
        {"time": f"2025-{m:02d}-01", "open": 140.0 + i * 2.4, "high": 141.0 + i * 2.5, "low": 139.0 + i * 2.3, "close": round(140.0 + i * 2.5, 2), "volume": 1000000 + i * 100000}
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
        for date, row in hist.iterrows():
            try:
                chart_data.append({
                    "time": date.strftime("%Y-%m-%d"),
                    "open": round(float(row.get("Open", 0)), 2),
                    "high": round(float(row.get("High", 0)), 2),
                    "low": round(float(row.get("Low", 0)), 2),
                    "close": round(float(row.get("Close", 0)), 2),
                    "volume": int(row.get("Volume", 0)),
                })
            except Exception:
                continue

        if not current_price and chart_data:
            current_price = chart_data[-1]["close"]

        return {
            "company_name": company_name,
            "current_price": current_price,
            "price_change_percent": change_pct,
            "chart_data": sorted(chart_data, key=lambda p: p["time"]),
        }
    except Exception:
        return MOCK_MARKET
