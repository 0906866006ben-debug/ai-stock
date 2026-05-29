"""Broad CAN SLIM technology universe source.

This module intentionally moves away from the hand-picked AI-tech winner list.
It enumerates a broad current TWSE/TPEx technology/electronics candidate pool
from FinMind's TaiwanStockInfo dataset. Residual caveat: the free FinMind stock
info list contains currently listed securities, so already-delisted names remain
excluded. The per-date tradable universe is therefore point-in-time for liquidity
and price history, but not a complete historical listed-security universe.
"""
from __future__ import annotations

import os
from typing import Any

import httpx

FINMIND_BASE = "https://api.finmindtrade.com/api/v4/data"

TECH_INDUSTRY_KEYWORDS = (
    "半導體",
    "電子零組件",
    "光電",
    "電腦及週邊",
    "電腦及週邊設備",
    "通信網路",
    "電子通路",
    "其他電子",
    "資訊服務",
)


def get_tech_universe_symbols() -> list[str]:
    """Return broad current TW technology/electronics common-stock symbols.

    The candidate pool is mechanical by industry category, but not fully PIT:
    delisted historical names are absent from FinMind's free current-security
    list. Use `get_universe_as_of()` to apply per-date PIT liquidity membership.
    """
    token = os.getenv("FINMIND_API_KEY") or os.getenv("FINMIND_TOKEN")
    rows = fetch_taiwan_stock_info(token)
    return parse_tech_universe_symbols(rows)


def get_all_universe_symbols(*, include_etf: bool = False) -> list[str]:
    """Return all currently-listed TW common-stock symbols across every industry.

    Unlike `get_tech_universe_symbols`, this drops the tech-industry filter so
    financials, traditional industry, shipping, etc. are all included. ETFs are
    excluded by default (they have no company fundamentals); pass include_etf=True
    to keep them (useful for price-only / OHLCV backfills). Same PIT caveat as the
    tech universe: already-delisted names are absent from FinMind's current list.
    """
    token = os.getenv("FINMIND_API_KEY") or os.getenv("FINMIND_TOKEN")
    rows = fetch_taiwan_stock_info(token)
    return parse_all_universe_symbols(rows, include_etf=include_etf)


def parse_all_universe_symbols(rows: list[dict[str, Any]], *, include_etf: bool = False) -> list[str]:
    symbols: set[str] = set()
    for row in rows:
        code = str(row.get("stock_id") or row.get("stock_code") or "").strip()
        raw_type = str(row.get("type") or "").lower()
        is_etf = "etf" in raw_type or "etn" in raw_type or code.startswith("00")
        if is_etf:
            if include_etf and code.isdigit() and len(code) in (4, 6):
                symbols.add(code)
            continue
        if _is_common_stock_code(code):
            symbols.add(code)
    return sorted(symbols)


def get_delisted_universe_symbols() -> list[str]:
    """Return already-delisted TW common-stock symbols (survivorship correction).

    FinMind's TaiwanStockDelisting (free) lists securities that left the market.
    Folding these back into the candidate pool — together with their historical
    OHLCV and the per-date staleness guard in `get_universe_as_of` — removes the
    survivorship bias that the current-only TaiwanStockInfo list introduces.
    """
    token = os.getenv("FINMIND_API_KEY") or os.getenv("FINMIND_TOKEN")
    rows = fetch_delisted_stocks(token)
    return parse_delisted_symbols(rows)


def fetch_delisted_stocks(token: str | None) -> list[dict[str, Any]]:
    """One ban-safe request to TaiwanStockDelisting. Returns [] on any failure."""
    if not token:
        return []
    try:
        with httpx.Client(timeout=30.0, headers={"User-Agent": "Mozilla/5.0"}) as client:
            response = client.get(
                FINMIND_BASE,
                params={"dataset": "TaiwanStockDelisting", "token": token},
            )
        if response.status_code != 200:
            return []
        payload = response.json()
    except Exception:
        return []
    if payload.get("status") != 200 or not payload.get("data"):
        return []
    return list(payload["data"])


def parse_delisted_symbols(rows: list[dict[str, Any]]) -> list[str]:
    """Extract delisted common-stock codes (4-digit, non-ETF). Dedup + sorted."""
    symbols: set[str] = set()
    for row in rows:
        code = str(row.get("stock_id") or row.get("stock_code") or "").strip()
        if _is_common_stock_code(code):
            symbols.add(code)
    return sorted(symbols)


def fetch_taiwan_stock_info(token: str | None) -> list[dict[str, Any]]:
    if not token:
        return []
    with httpx.Client(timeout=30.0) as client:
        response = client.get(
            FINMIND_BASE,
            params={"dataset": "TaiwanStockInfo", "token": token},
        )
        response.raise_for_status()
        payload = response.json()
    if payload.get("status") != 200 or not payload.get("data"):
        return []
    return list(payload["data"])


def parse_tech_universe_symbols(rows: list[dict[str, Any]]) -> list[str]:
    symbols: set[str] = set()
    for row in rows:
        code = str(row.get("stock_id") or row.get("stock_code") or "").strip()
        if not _is_common_stock_code(code):
            continue
        raw_type = str(row.get("type") or "").lower()
        if "etf" in raw_type or "etn" in raw_type:
            continue
        industry = str(row.get("industry_category") or row.get("industry") or "").strip()
        if not _is_tech_industry(industry):
            continue
        symbols.add(code)
    return sorted(symbols)


def _is_common_stock_code(code: str) -> bool:
    return len(code) == 4 and code.isdigit() and not code.startswith("00")


def _is_tech_industry(industry: str) -> bool:
    return any(keyword in industry for keyword in TECH_INDUSTRY_KEYWORDS)
