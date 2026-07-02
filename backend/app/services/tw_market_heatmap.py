"""Market sector heatmap (板塊熱力圖) from the local OHLCV store.

Computes each stock's latest 1-day % change straight from the downloaded
HistoricalDataStore (no per-stock FinMind call) and aggregates by industry.
Industry map comes from TaiwanStockInfo (one FinMind call, cached persistently;
falls back to "其他" when unavailable). Result cached once per UTC day.
"""
from __future__ import annotations

import os
from datetime import date, timedelta

from backend.app.services import file_cache
from backend.app.services.backtest.historical_data_store import HistoricalDataStore, DEFAULT_DB_PATH

_CACHE_NS = "market_heatmap"
_SECTOR_NS = "sector_map"


async def get_market_heatmap() -> dict:
    today = date.today().strftime("%Y-%m-%d")
    cached = file_cache.load(_CACHE_NS, today)
    if isinstance(cached, dict):
        return cached

    info_map = _stock_info_map()
    cutoff = (date.today() - timedelta(days=14)).strftime("%Y-%m-%d")
    store = HistoricalDataStore(DEFAULT_DB_PATH)

    by_stock: dict[str, list] = {}
    try:
        with store._connect() as conn:
            cur = conn.execute(
                """
                SELECT stock_id, date, close, turnover FROM (
                  SELECT stock_id, date, close, turnover,
                         ROW_NUMBER() OVER (PARTITION BY stock_id ORDER BY date DESC) AS rn
                  FROM ohlcv WHERE date >= ?
                ) WHERE rn <= 2 ORDER BY stock_id, date DESC
                """,
                (cutoff,),
            )
            for sid, d, close, turnover in cur.fetchall():
                by_stock.setdefault(str(sid), []).append((d, close, turnover))
    except Exception:
        by_stock = {}

    # (stock_id, name, change_pct, turnover) from local store when present,
    # otherwise from the free TWSE open API (cloud deploys have no local DB).
    records: list[tuple[str, str, float, float]] = []
    for sid, recs in by_stock.items():
        if len(recs) < 2 or recs[0][1] is None or not recs[1][1]:
            continue
        latest_close, prev_close, turnover = recs[0][1], recs[1][1], (recs[0][2] or 0.0)
        chg = (latest_close - prev_close) / prev_close * 100.0
        records.append((sid, "", chg, turnover))
    if not records:
        records = await _twse_day_all()
    if not records:
        return {"status": "no_data", "date": today, "sectors": [], "top_gainers": [], "top_losers": []}

    sectors: dict[str, dict] = {}
    movers: list[dict] = []
    for sid, fallback_name, chg, turnover in records:
        info = info_map.get(sid) or {}
        sec = info.get("i") or "其他"
        name = info.get("n") or fallback_name
        s = sectors.setdefault(sec, {"sector": sec, "count": 0, "up": 0, "down": 0, "sum_chg": 0.0, "turnover": 0.0})
        s["count"] += 1
        s["sum_chg"] += chg
        s["turnover"] += turnover
        if chg > 0:
            s["up"] += 1
        elif chg < 0:
            s["down"] += 1
        movers.append({"stock_id": sid, "name": name, "change_pct": round(chg, 2), "sector": sec, "turnover": turnover})

    out = [
        {
            "sector": s["sector"],
            "count": s["count"],
            "up": s["up"],
            "down": s["down"],
            "avg_change_pct": round(s["sum_chg"] / s["count"], 2),
            "turnover": s["turnover"],
        }
        for s in sectors.values()
        if s["count"]
    ]
    out.sort(key=lambda x: x["turnover"], reverse=True)
    movers.sort(key=lambda x: x["change_pct"], reverse=True)

    result = {
        "status": "ok" if out else "no_data",
        "date": today,
        "sectors": out,
        "top_gainers": movers[:10],
        "top_losers": movers[-10:][::-1],
    }
    if out:
        file_cache.save(_CACHE_NS, today, result)
    return result


async def _twse_day_all() -> list[tuple[str, str, float, float]]:
    """All-market daily quotes from the free TWSE open API (no key, TWSE-listed
    only). Returns (stock_id, name, change_pct, turnover) rows."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL",
                headers={"accept": "application/json"},
            )
            resp.raise_for_status()
            rows = resp.json()
    except Exception:
        return []

    records: list[tuple[str, str, float, float]] = []
    for row in rows:
        try:
            sid = str(row.get("Code") or "").strip()
            close = float(row.get("ClosingPrice") or 0)
            change = float(row.get("Change") or 0)
            turnover = float(row.get("TradeValue") or 0)
        except (TypeError, ValueError):
            continue
        prev = close - change
        if not sid or close <= 0 or prev <= 0:
            continue
        records.append((sid, str(row.get("Name") or "").strip(), change / prev * 100.0, turnover))
    return records


def _stock_info_map() -> dict[str, dict]:
    """stock_id -> {"i": industry_category, "n": stock_name} from TaiwanStockInfo
    (one FinMind call, cached persistently; {} when unavailable)."""
    cached = file_cache.load(_SECTOR_NS, "info")
    if isinstance(cached, dict) and cached:
        return cached
    try:
        from backend.app.services.strategy.canslim.universe_source import fetch_taiwan_stock_info
        token = os.getenv("FINMIND_API_KEY") or os.getenv("FINMIND_TOKEN")
        rows = fetch_taiwan_stock_info(token)
    except Exception:
        return {}
    mapping: dict[str, dict] = {}
    for row in rows:
        code = str(row.get("stock_id") or "").strip()
        industry = str(row.get("industry_category") or "").strip()
        name = str(row.get("stock_name") or "").strip()
        if code and (industry or name):
            mapping[code] = {"i": industry, "n": name}
    if mapping:
        file_cache.save(_SECTOR_NS, "info", mapping)
    return mapping
