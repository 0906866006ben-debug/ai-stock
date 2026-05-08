"""Taiwan stock directory from FinMind TaiwanStockInfo."""
import os
import httpx

FINMIND_BASE = "https://api.finmindtrade.com/api/v4/data"

_TYPE_MAP = {
    "twse": "上市",
    "tpex": "上櫃",
    "otc": "上櫃",
    "emerging": "興櫃",
    "esb": "創新板",
}

_MOCK_STOCKS = [
    {"stock_code": "2330", "company_name": "台積電", "market_type": "上市", "industry": "半導體"},
    {"stock_code": "2317", "company_name": "鴻海", "market_type": "上市", "industry": "電子"},
    {"stock_code": "2454", "company_name": "聯發科", "market_type": "上市", "industry": "半導體"},
    {"stock_code": "2412", "company_name": "中華電", "market_type": "上市", "industry": "電信"},
    {"stock_code": "2882", "company_name": "國泰金", "market_type": "上市", "industry": "金融"},
    {"stock_code": "2891", "company_name": "中信金", "market_type": "上市", "industry": "金融"},
    {"stock_code": "2303", "company_name": "聯電", "market_type": "上市", "industry": "半導體"},
    {"stock_code": "2308", "company_name": "台達電", "market_type": "上市", "industry": "電子"},
    {"stock_code": "0050", "company_name": "元大台灣50", "market_type": "ETF", "industry": None},
    {"stock_code": "0056", "company_name": "元大高股息", "market_type": "ETF", "industry": None},
    {"stock_code": "00878", "company_name": "國泰永續高股息", "market_type": "ETF", "industry": None},
    {"stock_code": "00929", "company_name": "復華台灣科技優息", "market_type": "ETF", "industry": None},
]


async def get_tw_stocks(
    q: str | None = None,
    stock_type: str | None = None,
    industry: str | None = None,
    limit: int = 100,
) -> dict:
    token = os.getenv("FINMIND_API_KEY")
    stocks = await _fetch_from_finmind(token) if token else _MOCK_STOCKS

    # Filter
    if q:
        q_lower = q.lower()
        stocks = [
            s for s in stocks
            if q_lower in s["stock_code"].lower() or q_lower in (s["company_name"] or "").lower()
        ]
    if stock_type:
        stocks = [s for s in stocks if s.get("market_type") == stock_type]
    if industry:
        stocks = [s for s in stocks if s.get("industry") == industry]

    total = len(stocks)
    stocks = stocks[:limit]

    return {
        "stocks": stocks,
        "total": total,
        "returned": len(stocks),
        "data_source": "live" if token else "mock",
    }


async def _fetch_from_finmind(token: str) -> list[dict]:
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                FINMIND_BASE,
                params={"dataset": "TaiwanStockInfo", "token": token},
            )
            resp.raise_for_status()
            payload = resp.json()

        if payload.get("status") != 200 or not payload.get("data"):
            return _MOCK_STOCKS

        raw_stocks = []
        for item in payload["data"]:
            raw_type = (item.get("type") or "").lower().strip()
            market_type = _TYPE_MAP.get(raw_type, raw_type.upper() if raw_type else "UNKNOWN")

            # Detect ETF by stock code or type name
            code = item.get("stock_id", "")
            if code.startswith("00") or "etf" in raw_type or "etn" in raw_type:
                market_type = "ETF"

            raw_stocks.append({
                "stock_code": code,
                "company_name": item.get("company_name", code),
                "market_type": market_type,
                "industry": item.get("industry_category") or None,
            })

        return raw_stocks if raw_stocks else _MOCK_STOCKS

    except Exception:
        return _MOCK_STOCKS
