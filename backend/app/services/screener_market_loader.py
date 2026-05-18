from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Optional

import httpx
import pandas as pd
import yfinance as yf

from backend.app.services.data_sources.source_models import MarketIndexLoadResult
from backend.app.services.finmind_market import FINMIND_BASE


async def load_taiex_history(days: int = 150) -> Optional[pd.DataFrame]:
    result = await load_taiex_history_with_source(days)
    return result.dataframe if result.available else None


async def load_taiex_history_with_source(days: int = 150) -> MarketIndexLoadResult:
    finmind = await _load_taiex_from_finmind(days)
    if finmind is not None and len(finmind) >= 60:
        return MarketIndexLoadResult(
            dataframe=finmind,
            source="finmind",
            available=True,
            fallback_used=False,
        )

    yfinance = _load_taiex_from_yfinance(days)
    if yfinance is not None and len(yfinance) >= 60:
        return MarketIndexLoadResult(
            dataframe=yfinance,
            source="yfinance",
            available=True,
            fallback_used=True,
            warnings=["market_index_finmind_unavailable"],
        )

    return MarketIndexLoadResult(
        dataframe=None,
        source="unavailable",
        available=False,
        fallback_used=True,
        warnings=["market_index_unavailable"],
    )


async def _load_taiex_from_finmind(days: int) -> Optional[pd.DataFrame]:
    token = os.getenv("FINMIND_API_KEY")
    if not token:
        return None

    end_date = date.today()
    start_date = end_date - timedelta(days=days)
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                FINMIND_BASE,
                params={
                    "dataset": "TaiwanStockPrice",
                    "data_id": "TAIEX",
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "token": token,
                },
            )
            resp.raise_for_status()
            payload = resp.json()
        if payload.get("status") != 200 or not payload.get("data"):
            return None
        rows = sorted(payload["data"], key=lambda item: item["date"])
        return pd.DataFrame([
            {
                "date": item["date"],
                "open": float(item["open"]),
                "high": float(item["max"]),
                "low": float(item["min"]),
                "close": float(item["close"]),
                "volume": int(item.get("Trading_Volume") or 0),
                "turnover_value": float(item.get("Trading_money") or 0),
            }
            for item in rows
        ])
    except Exception:
        return None


def _load_taiex_from_yfinance(days: int) -> Optional[pd.DataFrame]:
    end_date = date.today()
    start_date = end_date - timedelta(days=days)
    try:
        df = yf.download("^TWII", start=start_date, end=end_date, progress=False)
        if df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df.reset_index().rename(columns={
            "Date": "date",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        })
    except Exception:
        return None
