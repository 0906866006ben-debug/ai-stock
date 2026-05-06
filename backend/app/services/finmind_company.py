import os
import httpx

FINMIND_BASE = "https://api.finmindtrade.com/api/v4/data"

_TYPE_MAP = {
    "twse": "TWSE",
    "tpex": "TPEx",
    "otc": "TPEx",
}


def _mock_company(symbol: str) -> tuple[dict, bool]:
    return {"company_name": symbol, "market_type": "TWSE"}, True


async def get_tw_company_info(symbol: str) -> tuple[dict, bool]:
    """Return (company_dict, is_mock).

    company_dict keys: company_name (str), market_type ("TWSE" | "TPEx" | str).
    """
    token = os.getenv("FINMIND_API_KEY")
    if not token:
        return _mock_company(symbol)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                FINMIND_BASE,
                params={
                    "dataset": "TaiwanStockInfo",
                    "data_id": symbol,
                    "token": token,
                },
            )
            resp.raise_for_status()
            payload = resp.json()

        if payload.get("status") != 200 or not payload.get("data"):
            return _mock_company(symbol)

        info = payload["data"][0]
        raw_type = info.get("type", "").lower().strip()
        market_type = _TYPE_MAP.get(raw_type) or (raw_type.upper() if raw_type else "UNKNOWN")

        return {
            "company_name": info.get("company_name", symbol),
            "market_type": market_type,
        }, False

    except Exception:
        return _mock_company(symbol)
