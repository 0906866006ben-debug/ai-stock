"""Foreign-institution TAIEX-futures open-interest sentiment (free, market-level).

Reads `TaiwanFuturesInstitutionalInvestors` (free, 2018~) for the TX (台指期)
contract and reports the FOREIGN net open interest (long OI − short OI) plus its
recent trend — a market-wide positioning gauge for 大盤情緒. Informational only:
this does NOT feed the validated CANSLIM regime/M-pillar math.

Cached once per UTC day (positioning is daily EOD). Single request, no retry →
cannot trigger an IP ban; any problem degrades to {"status": "no_data"}.
"""
from __future__ import annotations

import os
from datetime import date, timedelta

import httpx

from backend.app.services import file_cache

FINMIND_BASE = "https://api.finmindtrade.com/api/v4/data"
_CACHE_NS = "futures_sentiment"


async def get_foreign_futures_sentiment() -> dict:
    today = date.today().strftime("%Y-%m-%d")
    cached = file_cache.load(_CACHE_NS, today)
    if isinstance(cached, dict):
        return cached

    token = os.getenv("FINMIND_API_KEY") or os.getenv("FINMIND_TOKEN")
    if not token:
        return {"status": "no_data"}

    start = (date.today() - timedelta(days=14)).strftime("%Y-%m-%d")
    try:
        async with httpx.AsyncClient(timeout=15.0, headers={"User-Agent": "Mozilla/5.0"}) as client:
            resp = await client.get(FINMIND_BASE, params={
                "dataset": "TaiwanFuturesInstitutionalInvestors",
                "data_id": "TX",
                "start_date": start,
                "token": token,
            })
        if resp.status_code != 200:  # 402 quota / 403 ban / 4xx → no retry, just skip
            return {"status": "no_data"}
        rows = resp.json().get("data") or []
    except Exception:
        return {"status": "no_data"}

    def _f(value) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    by_date: dict[str, float] = {}
    for row in rows:
        if str(row.get("futures_id")) != "TX":
            continue
        if "外資" not in str(row.get("institutional_investors") or ""):
            continue
        long_oi = _f(row.get("long_open_interest_balance_volume"))
        short_oi = _f(row.get("short_open_interest_balance_volume"))
        if long_oi is None or short_oi is None:
            continue
        by_date[str(row.get("date"))[:10]] = long_oi - short_oi

    if not by_date:
        return {"status": "no_data"}

    dates = sorted(by_date)
    net = by_date[dates[-1]]
    change = (net - by_date[dates[-2]]) if len(dates) >= 2 else None
    result = {
        "status": "ok",
        "date": dates[-1],
        "foreign_net_oi": int(net),
        "foreign_net_oi_change": (int(change) if change is not None else None),
        "direction": "net_long" if net > 0 else ("net_short" if net < 0 else "flat"),
        "trend": ("adding_long" if (change or 0) > 0 else "adding_short") if change else "stable",
    }
    file_cache.save(_CACHE_NS, today, result)
    return result
