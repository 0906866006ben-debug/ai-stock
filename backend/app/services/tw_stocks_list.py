"""Taiwan stock directory from FinMind or public exchange APIs."""
import os
import re
import httpx

from backend.app.services.data_sources import settings as data_source_settings
from backend.app.services.data_sources.tpex_client import fetch_tpex_mainboard_quotes

FINMIND_BASE = "https://api.finmindtrade.com/api/v4/data"
TWSE_STOCKS_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TPEX_STOCKS_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes"
PUBLIC_STOCK_CODE_RE = re.compile(r"^\d{4}$")

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
    warnings: list[str] = []
    public_stocks, public_report = await _fetch_from_public_openapi_with_report()
    token = os.getenv("FINMIND_API_KEY")
    finmind_stocks: list[dict] = []

    if public_stocks:
        stocks = public_stocks
        data_source = "public"
        source = "twse_tpex_official"
        fallback_used = False
    else:
        warnings.append("official_universe_unavailable")
        finmind_stocks = await _fetch_from_finmind(token) if token else []
        if finmind_stocks:
            stocks = finmind_stocks
            data_source = "live"
            source = "finmind"
            fallback_used = True
        elif data_source_settings.allow_mock_data():
            stocks = [dict(item, source="mock") for item in _MOCK_STOCKS]
            data_source = "mock"
            source = "mock"
            fallback_used = True
            warnings.append("mock_universe")
        else:
            stocks = []
            data_source = "unavailable"
            source = "unavailable"
            fallback_used = True
            warnings.append("universe_unavailable")

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
    source_counts = _universe_source_counts(stocks)
    stocks = stocks[:limit]

    return {
        "stocks": stocks,
        "total": total,
        "returned": len(stocks),
        "data_source": data_source,
        "source_report": {
            "source": source,
            "twse_count": source_counts["twse_official"],
            "tpex_count": source_counts["tpex_official"],
            "finmind_count": source_counts["finmind"],
            "mock_count": source_counts["mock"],
            "stock_count": total,
            "fallback_used": fallback_used,
            "warnings": warnings + public_report.get("warnings", []),
        },
    }


async def _fetch_from_finmind(token: str) -> list[dict]:
    if not token:
        return []

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                FINMIND_BASE,
                params={"dataset": "TaiwanStockInfo", "token": token},
            )
            resp.raise_for_status()
            payload = resp.json()

        if payload.get("status") != 200 or not payload.get("data"):
            return []

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
                "company_name": item.get("stock_name") or item.get("company_name", code),
                "market_type": market_type,
                "industry": item.get("industry_category") or None,
                "source": "finmind",
            })

        return raw_stocks

    except Exception:
        return []


async def _fetch_from_public_openapi() -> list[dict]:
    stocks, _report = await _fetch_from_public_openapi_with_report()
    return stocks


async def _fetch_from_public_openapi_with_report() -> tuple[list[dict], dict]:
    warnings: list[str] = []
    twse_data: list[dict] = []
    tpex_data: list[dict] = []
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            twse_resp = await client.get(TWSE_STOCKS_URL)
            twse_resp.raise_for_status()
            twse_data = twse_resp.json()
    except Exception:
        warnings.append("twse_universe_unavailable")

    try:
        tpex_data = await fetch_tpex_mainboard_quotes()
    except Exception:
        warnings.append("tpex_universe_unavailable")

    stocks: list[dict] = []
    for item in twse_data:
        code = str(item.get("Code") or "").strip()
        if _is_common_stock_code(code):
            stocks.append({
                "stock_code": code,
                "company_name": item.get("Name") or code,
                "market_type": "上市",
                "industry": None,
                "source": "twse_official",
            })

    for item in tpex_data:
        code = str(item.get("stock_id") or item.get("SecuritiesCompanyCode") or "").strip()
        if _is_common_stock_code(code):
            stocks.append({
                "stock_code": code,
                "company_name": item.get("stock_name") or item.get("CompanyName") or code,
                "market_type": "上櫃",
                "industry": None,
                "source": "tpex_official",
            })

    unique = _dedupe_stocks(stocks)
    return unique, {
        "warnings": warnings,
        "twse_count": sum(1 for item in unique if item.get("source") == "twse_official"),
        "tpex_count": sum(1 for item in unique if item.get("source") == "tpex_official"),
    }


def _universe_source_counts(stocks: list[dict]) -> dict[str, int]:
    counts = {"twse_official": 0, "tpex_official": 0, "finmind": 0, "mock": 0}
    for stock in stocks:
        source = str(stock.get("source") or "")
        if source in counts:
            counts[source] += 1
    return counts


def _is_common_stock_code(code: str) -> bool:
    return bool(PUBLIC_STOCK_CODE_RE.fullmatch(code)) and not code.startswith("00")


def _dedupe_stocks(stocks: list[dict]) -> list[dict]:
    seen: set[str] = set()
    unique: list[dict] = []
    for stock in stocks:
        code = str(stock.get("stock_code") or "").strip()
        if not code or code in seen:
            continue
        seen.add(code)
        unique.append(stock)
    return unique
