from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import pandas as pd

from backend.app.services.finmind_market import get_tw_price_history
from backend.app.services.tw_financial_metrics import fetch_real_metrics
from backend.app.services.tw_stocks_list import get_tw_stocks
from backend.screeners.multi_factor_surge.config import CONFIG


logger = logging.getLogger(__name__)
FundamentalsProvider = Callable[[str], Awaitable[dict[str, Any] | None]]


@dataclass
class StockContext:
    stock_id: str
    stock_name: str
    market_type: str | None
    ohlcv: pd.DataFrame
    fundamentals: dict[str, Any] | None
    missing_data: list[str] = field(default_factory=list)
    data_quality_flags: list[str] = field(default_factory=list)


def canonicalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = df.columns.get_level_values(0)
    column_map: dict[Any, str] = {}
    for col in df.columns:
        key = str(col).strip().lower()
        if key in {"date", "time"}:
            column_map[col] = "date"
        elif key in {"open"}:
            column_map[col] = "open"
        elif key in {"high", "max"}:
            column_map[col] = "high"
        elif key in {"low", "min"}:
            column_map[col] = "low"
        elif key == "close":
            column_map[col] = "close"
        elif key in {"volume", "trading_volume"}:
            column_map[col] = "volume"
        elif key in {"turnover", "turnover_value", "trading_money"}:
            column_map[col] = "turnover_value"
    normalized = df.rename(columns=column_map).copy()
    required = ["open", "high", "low", "close", "volume"]
    missing = [col for col in required if col not in normalized.columns]
    if missing:
        raise ValueError(f"Missing OHLCV columns: {', '.join(missing)}")
    for col in required + (["turnover_value"] if "turnover_value" in normalized.columns else []):
        normalized[col] = pd.to_numeric(normalized[col], errors="coerce")
    normalized = normalized.dropna(subset=required).reset_index(drop=True)
    return normalized


def candles_to_dataframe(candles: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": item.get("time") or item.get("date") or item.get("Date"),
                "open": item.get("open") or item.get("Open"),
                "high": item.get("high") or item.get("High") or item.get("max"),
                "low": item.get("low") or item.get("Low") or item.get("min"),
                "close": item.get("close") or item.get("Close"),
                "volume": item.get("volume") or item.get("Volume") or item.get("Trading_Volume"),
                "turnover_value": item.get("turnover_value") or item.get("Turnover") or item.get("Trading_money"),
            }
            for item in candles
        ]
    )


async def load_universe(market: str, scan_limit: int | None = None) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    payload = await get_tw_stocks(limit=scan_limit or int(CONFIG["universe"]["default_scan_limit"]))
    raw = payload.get("stocks", [])
    warnings = [
        "common_stock_filter_heuristic: security_type field unavailable, using code+name pattern fallback"
    ]
    market_filtered = [item for item in raw if _market_matches(item.get("market_type"), market)]
    filtered: list[dict[str, Any]] = []
    breakdown = {"etf": 0, "warrant": 0, "preferred": 0, "ky": 0, "name_keyword": 0, "industry": 0, "market": 0}
    for item in market_filtered:
        excluded, reason = common_stock_exclusion_reason(item)
        if excluded:
            breakdown[reason] = breakdown.get(reason, 0) + 1
            continue
        filtered.append(item)
    stats = {
        "raw_universe_size": len(raw),
        "market_filter_count": len(market_filtered),
        "common_stock_filter_count": len(filtered),
        "excluded_by_pattern_count": breakdown,
        "data_source": payload.get("data_source", "unknown"),
    }
    return filtered, stats, warnings


def _market_matches(market_type: Any, market: str) -> bool:
    if market == "all":
        return market_type in CONFIG["universe"]["twse_values"] or market_type in CONFIG["universe"]["tpex_values"]
    if market == "twse":
        return market_type in CONFIG["universe"]["twse_values"]
    if market == "tpex":
        return market_type in CONFIG["universe"]["tpex_values"]
    return False


def common_stock_exclusion_reason(item: dict[str, Any]) -> tuple[bool, str]:
    code = str(item.get("stock_code") or item.get("code") or "").strip()
    name = str(item.get("company_name") or item.get("name") or "")
    industry = str(item.get("industry") or "")
    market_type = str(item.get("market_type") or "")
    if market_type in CONFIG["universe"]["excluded_market_values"]:
        return True, "market"
    if name.endswith(CONFIG["universe"]["ky_name_suffix"]) or code.endswith(CONFIG["universe"]["ky_code_suffix"]):
        return True, "ky"
    if code.startswith(tuple(CONFIG["universe"]["exclude_code_prefixes"])) and 4 <= len(code) <= 6:
        return True, "etf"
    if len(code) >= 6 and code.startswith(tuple(CONFIG["universe"]["warrant_prefixes"])):
        return True, "warrant"
    if re.search(r"[A-Za-z]$", code) and code.endswith(tuple(CONFIG["universe"]["preferred_suffixes"])):
        return True, "preferred"
    if any(keyword in name for keyword in CONFIG["universe"]["name_keywords"]):
        return True, "name_keyword"
    if any(keyword.lower() in industry.lower() for keyword in CONFIG["universe"]["industry_keywords"]):
        return True, "industry"
    return False, ""


async def build_stock_context(
    item: dict[str, Any],
    *,
    fundamentals_provider: FundamentalsProvider | None = None,
) -> StockContext:
    stock_id = str(item.get("stock_code") or item.get("code") or "").strip()
    stock_name = str(item.get("company_name") or item.get("name") or stock_id)
    candles, _is_mock = await get_tw_price_history(stock_id, 260)
    ohlcv = canonicalize_ohlcv(candles_to_dataframe(candles))
    fundamentals = await load_fundamentals(stock_id, provider=fundamentals_provider)
    return StockContext(
        stock_id=stock_id,
        stock_name=stock_name,
        market_type=item.get("market_type"),
        ohlcv=ohlcv,
        fundamentals=fundamentals,
    )


async def load_fundamentals(stock_id: str, *, provider: FundamentalsProvider | None = None) -> dict[str, Any] | None:
    try:
        payload = await (provider(stock_id) if provider else fetch_real_metrics(stock_id))
    except Exception as exc:
        logger.warning("fundamentals unavailable for %s: %s", stock_id, exc)
        return None
    if not payload:
        return None
    if payload.get("is_mock") or payload.get("source") == "mock":
        return None
    return payload
