"""Taiwan dividend & earnings calendar.

Dividends: real per-stock data via FinMind `TaiwanStockDividend`.
Earnings: hybrid — past filings from `TaiwanStockFinancialStatements`,
          upcoming windows derived from regulatory deadlines.
"""
from __future__ import annotations

import os
import asyncio
import httpx
from datetime import date, datetime, timedelta

FINMIND_BASE = "https://api.finmindtrade.com/api/v4/data"

# TW regulatory filing deadlines (month, day) for each fiscal quarter
_QUARTER_DEADLINES = {
    1: (5, 15),   # Q1 by May 15
    2: (8, 14),   # Q2 by Aug 14
    3: (11, 14),  # Q3 by Nov 14
    4: (3, 31),   # FY by Mar 31 of next year
}

# ── Mock data ────────────────────────────────────────────────────────────────

_MOCK_DIVIDENDS = [
    {
        "stock_code": "2330",
        "company_name": "台積電",
        "ex_date": "2026-06-19",
        "payment_date": "2026-07-10",
        "announcement_date": "2026-04-18",
        "cash_per_share": 4.5,
        "stock_per_share": 0.0,
        "type": "cash",
    },
    {
        "stock_code": "0056",
        "company_name": "元大高股息",
        "ex_date": "2026-07-21",
        "payment_date": "2026-08-13",
        "announcement_date": "2026-06-30",
        "cash_per_share": 0.85,
        "stock_per_share": 0.0,
        "type": "cash",
    },
    {
        "stock_code": "00878",
        "company_name": "國泰永續高股息",
        "ex_date": "2026-05-19",
        "payment_date": "2026-06-12",
        "announcement_date": "2026-04-25",
        "cash_per_share": 0.5,
        "stock_per_share": 0.0,
        "type": "cash",
    },
]


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _fetch(dataset: str, token: str, params: dict | None = None) -> list[dict]:
    full_params = {"dataset": dataset, "token": token, **(params or {})}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(FINMIND_BASE, params=full_params)
            resp.raise_for_status()
            payload = resp.json()
        if payload.get("status") == 200:
            return payload.get("data", [])
    except Exception:
        pass
    return []


def _classify_dividend(cash: float, stock: float) -> str:
    if cash > 0 and stock > 0:
        return "mixed"
    if stock > 0:
        return "stock"
    return "cash"


def _normalize_dividend(row: dict) -> dict:
    cash = float(row.get("CashEarningsDistribution") or 0)
    stock = float(row.get("StockEarningsDistribution") or 0)
    return {
        "stock_code": row.get("stock_id", ""),
        "company_name": None,
        "ex_date": row.get("CashExDividendTradingDate") or row.get("StockExDividendTradingDate") or None,
        "payment_date": row.get("CashDividendPaymentDate") or None,
        "announcement_date": row.get("date"),
        "cash_per_share": cash if cash else None,
        "stock_per_share": stock if stock else None,
        "type": _classify_dividend(cash, stock),
    }


# ── Dividends ────────────────────────────────────────────────────────────────

async def get_dividend_events(
    symbol: str | None,
    start: date,
    end: date,
) -> dict:
    token = os.getenv("FINMIND_API_KEY")
    if not token:
        return _mock_dividends_filtered(symbol, start, end)

    params: dict = {
        "start_date": start.strftime("%Y-%m-%d"),
        "end_date": end.strftime("%Y-%m-%d"),
    }
    if symbol:
        params["data_id"] = symbol

    raw = await _fetch("TaiwanStockDividend", token, params)
    if not raw:
        return _mock_dividends_filtered(symbol, start, end)

    events = [_normalize_dividend(r) for r in raw]
    # Filter out rows with no useful date
    events = [e for e in events if e.get("ex_date") or e.get("payment_date")]
    # Sort by ex_date
    events.sort(key=lambda e: e.get("ex_date") or e.get("payment_date") or "")
    return {"events": events, "data_source": "live"}


def _mock_dividends_filtered(symbol: str | None, start: date, end: date) -> dict:
    s = start.strftime("%Y-%m-%d")
    e = end.strftime("%Y-%m-%d")
    events = [
        ev for ev in _MOCK_DIVIDENDS
        if (not symbol or ev["stock_code"] == symbol)
        and (ev.get("ex_date") and s <= ev["ex_date"] <= e)
    ]
    return {"events": events, "data_source": "mock"}


def get_next_dividend_for(symbol: str, today: date | None = None) -> dict | None:
    """Synchronous helper that uses mock list — used to enrich /analyze/tw fast.

    Returns the nearest upcoming dividend event for the given symbol, or None.
    """
    today = today or date.today()
    today_str = today.strftime("%Y-%m-%d")
    upcoming = [
        ev for ev in _MOCK_DIVIDENDS
        if ev["stock_code"] == symbol
        and ev.get("ex_date")
        and ev["ex_date"] >= today_str
    ]
    if not upcoming:
        return None
    upcoming.sort(key=lambda e: e["ex_date"])
    return upcoming[0]


async def get_next_dividend_live(symbol: str) -> dict | None:
    """Async version — checks FinMind for the nearest upcoming ex-date."""
    today = date.today()
    end = today + timedelta(days=180)
    result = await get_dividend_events(symbol, today, end)
    events = [e for e in result["events"] if e.get("ex_date") and e["ex_date"] >= today.strftime("%Y-%m-%d")]
    if not events:
        return None
    events.sort(key=lambda e: e["ex_date"])
    return events[0]


# ── Earnings ─────────────────────────────────────────────────────────────────

def _quarter_deadline(year: int, quarter: int) -> date:
    if quarter not in _QUARTER_DEADLINES:
        return date(year, 12, 31)
    month, day = _QUARTER_DEADLINES[quarter]
    if quarter == 4:
        return date(year + 1, month, day)
    return date(year, month, day)


def _build_window_events(symbol: str | None, today: date) -> list[dict]:
    """Compute the next 4 quarter-end deadlines as upcoming events."""
    events: list[dict] = []
    year = today.year
    for q in range(1, 5):
        deadline = _quarter_deadline(year, q)
        if deadline >= today:
            events.append({
                "stock_code": symbol or "",
                "fiscal_year": year,
                "fiscal_quarter": q,
                "deadline": deadline.strftime("%Y-%m-%d"),
                "actual_filing_date": None,
                "eps": None,
                "is_upcoming": True,
            })
    # Add Q1 of next year if needed to ensure ≥4 events
    if len(events) < 4:
        for q in range(1, 5 - len(events) + 1):
            deadline = _quarter_deadline(year + 1, q)
            events.append({
                "stock_code": symbol or "",
                "fiscal_year": year + 1,
                "fiscal_quarter": q,
                "deadline": deadline.strftime("%Y-%m-%d"),
                "actual_filing_date": None,
                "eps": None,
                "is_upcoming": True,
            })
            if len(events) >= 4:
                break
    return events[:4]


async def get_earnings_events(symbol: str | None) -> dict:
    today = date.today()
    upcoming = _build_window_events(symbol, today)

    if not symbol:
        return {"events": upcoming, "data_source": "mock"}

    token = os.getenv("FINMIND_API_KEY")
    if not token:
        return {"events": upcoming, "data_source": "mock"}

    # Pull last 18 months of financial statements to backfill past quarters
    start = (today - timedelta(days=540)).strftime("%Y-%m-%d")
    end = today.strftime("%Y-%m-%d")
    raw = await _fetch("TaiwanStockFinancialStatements", token, {
        "data_id": symbol, "start_date": start, "end_date": end,
    })
    past = _extract_past_filings(raw, symbol)

    return {
        "events": past + upcoming,
        "data_source": "live" if raw else "mock",
    }


def _extract_past_filings(raw: list[dict], symbol: str) -> list[dict]:
    """Extract per-quarter filings with EPS from FinancialStatements rows."""
    by_quarter: dict[tuple[int, int], dict] = {}
    for row in raw:
        date_str = row.get("date", "")
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            continue
        # Filing date is typically the quarter end + reporting lag; we approximate with `date`.
        # Determine fiscal quarter from the date
        q = (d.month - 1) // 3 + 1
        key = (d.year, q)

        type_field = (row.get("type") or "").lower()
        value = row.get("value")
        if type_field == "eps" and value is not None:
            by_quarter.setdefault(key, {})["eps"] = float(value)
            by_quarter[key]["filing_date"] = date_str

    events = []
    for (year, q), info in sorted(by_quarter.items()):
        events.append({
            "stock_code": symbol,
            "fiscal_year": year,
            "fiscal_quarter": q,
            "deadline": _quarter_deadline(year, q).strftime("%Y-%m-%d"),
            "actual_filing_date": info.get("filing_date"),
            "eps": info.get("eps"),
            "is_upcoming": False,
        })
    return events
