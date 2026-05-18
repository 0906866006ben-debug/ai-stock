from __future__ import annotations

from datetime import date
from typing import Any, Optional

import httpx


TPEX_OPENAPI_BASE = "https://www.tpex.org.tw/openapi/v1"
TPEX_MAINBOARD_QUOTES_PATH = "/tpex_mainboard_quotes"


def _parse_number(value: Any) -> Optional[float]:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text or text in {"-", "--", "----"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_int(value: Any) -> Optional[int]:
    number = _parse_number(value)
    return int(number) if number is not None else None


def _parse_tpex_date(value: Any) -> str:
    text = str(value or "").strip()
    if len(text) == 7 and text.isdigit():
        year = int(text[:3]) + 1911
        month = int(text[3:5])
        day = int(text[5:7])
        return date(year, month, day).isoformat()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return text


def normalize_tpex_mainboard_quote(row: dict[str, Any]) -> Optional[dict[str, Any]]:
    stock_id = str(row.get("SecuritiesCompanyCode") or "").strip()
    stock_name = str(row.get("CompanyName") or stock_id).strip()
    if not stock_id:
        return None

    open_price = _parse_number(row.get("Open"))
    high = _parse_number(row.get("High"))
    low = _parse_number(row.get("Low"))
    close = _parse_number(row.get("Close"))
    volume = _parse_int(row.get("TradingShares"))
    turnover_value = _parse_number(row.get("TransactionAmount"))

    if close is None:
        return None

    return {
        "stock_id": stock_id,
        "stock_name": stock_name,
        "date": _parse_tpex_date(row.get("Date")),
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "turnover_value": turnover_value,
        "source": "tpex_official",
        "turnover_source": "official" if turnover_value is not None else "missing",
        "is_official": True,
    }


async def fetch_tpex_mainboard_quotes(timeout: float = 20.0) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(
            f"{TPEX_OPENAPI_BASE}{TPEX_MAINBOARD_QUOTES_PATH}",
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        payload = response.json()

    if not isinstance(payload, list):
        return []

    normalized: list[dict[str, Any]] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        item = normalize_tpex_mainboard_quote(row)
        if item is not None:
            normalized.append(item)
    return normalized


async def fetch_tpex_mainboard_quote_map(timeout: float = 20.0) -> dict[str, dict[str, Any]]:
    quotes = await fetch_tpex_mainboard_quotes(timeout=timeout)
    return {quote["stock_id"]: quote for quote in quotes}

