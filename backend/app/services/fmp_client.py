import os
import httpx

FMP_BASE = "https://financialmodelingprep.com/stable"


async def fmp_get(endpoint: str, params: dict | None = None) -> list | dict:
    api_key = os.getenv("FMP_API_KEY", "")
    if not api_key:
        return []

    p: dict = {"apikey": api_key}
    if params:
        p.update(params)

    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.get(f"{FMP_BASE}/{endpoint}", params=p)
            resp.raise_for_status()
            data = resp.json()
            return data if data else []
    except Exception:
        return []
