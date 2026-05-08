import asyncio

from .fmp_client import fmp_get

_INDICATORS = [
    ("GDP", "GDP"),
    ("CPI", "CPI"),
    ("unemploymentRate", "Unemployment Rate"),
    ("federalFunds", "Federal Funds Rate"),
]

MOCK_MARKET_OVERVIEW = {
    "economic_indicators": [
        {"name": "GDP", "label": "GDP", "value": None, "date": None},
        {"name": "CPI", "label": "CPI", "value": None, "date": None},
        {"name": "unemploymentRate", "label": "Unemployment Rate", "value": None, "date": None},
        {"name": "federalFunds", "label": "Federal Funds Rate", "value": None, "date": None},
    ],
    "top_stocks": [],
    "data_source": "mock",
}


async def get_market_overview() -> dict:
    """Fetch economic indicators and top actively traded stocks."""
    econ_coros = [
        fmp_get("economic-indicators", {"name": key, "limit": 1})
        for key, _ in _INDICATORS
    ]
    screener_coro = fmp_get("company-screener", {
        "limit": 10,
        "isActivelyTrading": "true",
        "isEtf": "false",
        "country": "US",
    })

    all_results = await asyncio.gather(*econ_coros, screener_coro, return_exceptions=True)
    econ_results = all_results[: len(_INDICATORS)]
    screener_result = all_results[-1]

    economic_indicators = []
    for (key, label), data in zip(_INDICATORS, econ_results):
        if isinstance(data, list) and data:
            item = data[0]
            economic_indicators.append({
                "name": key,
                "label": label,
                "value": item.get("value"),
                "date": item.get("date"),
            })
        else:
            economic_indicators.append({"name": key, "label": label, "value": None, "date": None})

    top_stocks = []
    if isinstance(screener_result, list):
        for s in screener_result[:10]:
            top_stocks.append({
                "symbol": s.get("symbol"),
                "company_name": s.get("companyName"),
                "price": s.get("price"),
                "market_cap": s.get("marketCap"),
                "sector": s.get("sector"),
                "volume": s.get("volume"),
                "beta": s.get("beta"),
            })

    has_data = any(i["value"] is not None for i in economic_indicators) or bool(top_stocks)

    return {
        "economic_indicators": economic_indicators,
        "top_stocks": top_stocks,
        "data_source": "live" if has_data else "mock",
    }
