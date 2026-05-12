import yfinance as yf

MOCK_FINANCIALS = {
    "market_cap": "N/A (demo)",
    "pe_ratio": "N/A (demo)",
    "52_week_high": "N/A (demo)",
    "52_week_low": "N/A (demo)",
    "volume": "N/A (demo)",
}


def _format_cap(value: float) -> str:
    if value >= 1e12:
        return f"${value / 1e12:.2f}T"
    if value >= 1e9:
        return f"${value / 1e9:.2f}B"
    if value >= 1e6:
        return f"${value / 1e6:.2f}M"
    return f"${value:,.0f}"


async def get_financial_data(symbol: str) -> dict:
    try:
        info = yf.Ticker(symbol).info or {}
        result: dict[str, str] = {}

        if cap := info.get("marketCap"):
            result["market_cap"] = _format_cap(float(cap))
        if pe := info.get("trailingPE"):
            result["pe_ratio"] = f"{float(pe):.1f}"
        if high := info.get("fiftyTwoWeekHigh"):
            result["52_week_high"] = f"${float(high):.2f}"
        if low := info.get("fiftyTwoWeekLow"):
            result["52_week_low"] = f"${float(low):.2f}"
        if vol := info.get("volume"):
            result["volume"] = f"{int(vol):,}"
        if div := info.get("dividendYield"):
            result["dividend_yield"] = f"{float(div) * 100:.2f}%"

        return result if result else MOCK_FINANCIALS
    except Exception:
        return MOCK_FINANCIALS
