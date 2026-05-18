import os
import time
import asyncio
import httpx
from datetime import date, datetime, timedelta, timezone
import pandas as pd
import yfinance as yf

from backend.app.services.data_sources import settings as data_source_settings
from backend.app.services.data_sources.source_models import OhlcvLoadResult, SourceInfo

FINMIND_BASE = "https://api.finmindtrade.com/api/v4/data"
_FINMIND_DISABLED_UNTIL = 0.0
_FINMIND_DISABLE_SECONDS = 3600

# Realistic mock prices for common Taiwan stocks
_MOCK_PRICES = {
    "2330": {"base": 2290, "volume": 50_000_000},    # TSMC
    "0050": {"base": 130, "volume": 5_000_000},      # 0050 ETF
    "0056": {"base": 50, "volume": 8_000_000},       # 0056 ETF
    "2454": {"base": 1180, "volume": 15_000_000},    # MediaTek
    "2317": {"base": 155, "volume": 80_000_000},     # Foxconn
}


def _generate_mock_candles(symbol: str, days: int = 120) -> list[dict]:
    """Generate realistic mock OHLCV data for a given symbol."""
    prices = _MOCK_PRICES.get(symbol, {"base": 100, "volume": 1_000_000})
    base_price = prices["base"]
    base_volume = prices["volume"]

    candles = []
    current_price = base_price

    for i in range(days, 0, -1):
        from datetime import date, timedelta
        trading_date = (date.today() - timedelta(days=i)).strftime("%Y-%m-%d")

        # Add realistic daily movement (-2% to +2%)
        daily_change = (i % 13 - 6) * 0.3 / 100  # Cyclical pattern
        open_price = current_price
        close_price = current_price * (1 + daily_change)
        high_price = max(open_price, close_price) * 1.01
        low_price = min(open_price, close_price) * 0.99

        # Add volume variation
        volume = int(base_volume * (0.8 + (i % 7) * 0.05))

        candles.append({
            "time": trading_date,
            "open": round(open_price, 2),
            "high": round(high_price, 2),
            "low": round(low_price, 2),
            "close": round(close_price, 2),
            "volume": volume,
        })

        current_price = close_price

    return candles


_MOCK_CANDLES = _generate_mock_candles("2330")

_MOCK_LAST = _MOCK_CANDLES[-1]
_MOCK_PREV = _MOCK_CANDLES[-2]
_MOCK_CHANGE = round(
    (_MOCK_LAST["close"] - _MOCK_PREV["close"]) / _MOCK_PREV["close"] * 100, 2
)

_MOCK_RESULT: dict = {
    "chart_data": _MOCK_CANDLES,
    "current_price": _MOCK_LAST["close"],
    "price_change_percent": _MOCK_CHANGE,
    "volume": _MOCK_LAST["volume"],
}


def _finmind_disabled() -> bool:
    return time.time() < _FINMIND_DISABLED_UNTIL


def get_finmind_rate_limit_state() -> dict:
    disabled = _finmind_disabled()
    disabled_until = (
        datetime.fromtimestamp(_FINMIND_DISABLED_UNTIL, tz=timezone.utc).isoformat()
        if disabled
        else None
    )
    return {
        "finmind_rate_limited": disabled,
        "finmind_disabled_until": disabled_until,
    }


def _disable_finmind_temporarily() -> None:
    global _FINMIND_DISABLED_UNTIL
    _FINMIND_DISABLED_UNTIL = time.time() + _FINMIND_DISABLE_SECONDS


def _mock_market(symbol: str) -> tuple[dict, bool]:
    """Generate realistic mock market data for a Taiwan stock."""
    candles = _generate_mock_candles(symbol)
    if not candles:
        return _MOCK_RESULT, True

    last = candles[-1]
    prev = candles[-2] if len(candles) > 1 else last
    change = round((last["close"] - prev["close"]) / prev["close"] * 100, 2)

    return {
        "chart_data": candles,
        "current_price": last["close"],
        "price_change_percent": change,
        "volume": last["volume"],
    }, True


async def get_tw_price_history(symbol: str, days: int) -> tuple[list[dict], bool]:
    """Fetch raw daily candles for the past `days` days. Returns (candles, is_mock)."""
    result = await get_tw_price_history_with_source(symbol, days)
    return result.candles, result.source_info.is_mock_data


async def get_tw_price_history_with_source(symbol: str, days: int) -> OhlcvLoadResult:
    """Fetch daily candles with explicit source metadata."""
    warnings: list[str] = []
    if data_source_settings.is_yfinance_only_mode():
        warnings.append("yfinance_only_mode")
        return await asyncio.to_thread(_get_yfinance_price_history_with_source, symbol, days, warnings)

    token = os.getenv("FINMIND_API_KEY")
    if not token or _finmind_disabled():
        if _finmind_disabled():
            warnings.append("finmind_temporarily_disabled")
        elif not token:
            warnings.append("finmind_token_missing")
        return await asyncio.to_thread(_get_yfinance_price_history_with_source, symbol, days, warnings)

    end_date = date.today().strftime("%Y-%m-%d")
    start_date = (date.today() - timedelta(days=days)).strftime("%Y-%m-%d")

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                FINMIND_BASE,
                params={
                    "dataset": "TaiwanStockPrice",
                    "data_id": symbol,
                    "start_date": start_date,
                    "end_date": end_date,
                    "token": token,
                },
            )
            resp.raise_for_status()
            payload = resp.json()
        if payload.get("status") != 200:
            if payload.get("status") in {402, 429} or "upper limit" in str(payload.get("msg", "")).lower():
                _disable_finmind_temporarily()
                warnings.append("finmind_rate_limited")
            else:
                warnings.append("finmind_unavailable")
            return await asyncio.to_thread(_get_yfinance_price_history_with_source, symbol, days, warnings)
        if not payload.get("data"):
            warnings.append("finmind_empty")
            return await asyncio.to_thread(_get_yfinance_price_history_with_source, symbol, days, warnings)
        rows = sorted(payload["data"], key=lambda r: r["date"])
        candles = [
            {
                "time": r["date"],
                "open": float(r["open"]),
                "high": float(r["max"]),
                "low": float(r["min"]),
                "close": float(r["close"]),
                "volume": int(r["Trading_Volume"]),
                "turnover_value": float(r["Trading_money"]) if r.get("Trading_money") is not None else None,
            }
            for r in rows
        ]
        if candles:
            has_turnover = any(item.get("turnover_value") is not None for item in candles)
            source_info = SourceInfo(
                ohlcv_source="finmind",
                turnover_source="finmind_trading_money" if has_turnover else "estimated",
                market_index_source="unavailable",
                is_mock_data=False,
                bars_count=len(candles),
                data_warnings=list(warnings),
            )
            return OhlcvLoadResult(
                candles=candles,
                source_info=source_info,
                **get_finmind_rate_limit_state(),
            )
        warnings.append("finmind_empty")
        return await asyncio.to_thread(_get_yfinance_price_history_with_source, symbol, days, warnings)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in {402, 429}:
            _disable_finmind_temporarily()
            warnings.append("finmind_rate_limited")
        else:
            warnings.append("finmind_http_error")
        return await asyncio.to_thread(_get_yfinance_price_history_with_source, symbol, days, warnings)
    except Exception:
        warnings.append("finmind_error")
        return await asyncio.to_thread(_get_yfinance_price_history_with_source, symbol, days, warnings)


def _get_yfinance_price_history_with_source(symbol: str, days: int, warnings: list[str] | None = None) -> OhlcvLoadResult:
    warnings = list(warnings or [])
    candles, _is_mock = _get_yfinance_price_history(symbol, days, allow_mock=False)
    if len(candles) >= 60:
        if data_source_settings.is_yfinance_only_mode() and "yfinance_only_mode" not in warnings:
            warnings.append("yfinance_only_mode")
        if "turnover_value_estimated" not in warnings:
            warnings.append("turnover_value_estimated")
        source_info = SourceInfo(
            ohlcv_source="yfinance",
            turnover_source="estimated",
            is_mock_data=False,
            bars_count=len(candles),
            data_warnings=warnings,
        )
        return OhlcvLoadResult(
            candles=candles,
            source_info=source_info,
            **get_finmind_rate_limit_state(),
        )

    if data_source_settings.allow_mock_data():
        mock_candles = _generate_mock_candles(symbol, days)
        mock_warnings = list(warnings)
        if "mock_ohlcv" not in mock_warnings:
            mock_warnings.append("mock_ohlcv")
        if "turnover_value_estimated" not in mock_warnings:
            mock_warnings.append("turnover_value_estimated")
        source_info = SourceInfo(
            ohlcv_source="mock",
            turnover_source="estimated",
            is_mock_data=True,
            bars_count=len(mock_candles),
            data_warnings=mock_warnings,
        )
        return OhlcvLoadResult(
            candles=mock_candles,
            source_info=source_info,
            **get_finmind_rate_limit_state(),
        )

    unavailable_warnings = list(warnings)
    if "insufficient_data" not in unavailable_warnings:
        unavailable_warnings.append("insufficient_data")
    source_info = SourceInfo(
        ohlcv_source="unavailable",
        turnover_source="missing",
        is_mock_data=False,
        bars_count=len(candles),
        data_warnings=unavailable_warnings,
    )
    return OhlcvLoadResult(
        candles=candles,
        source_info=source_info,
        error="insufficient_data",
        **get_finmind_rate_limit_state(),
    )


def _get_yfinance_price_history(symbol: str, days: int, allow_mock: bool = True) -> tuple[list[dict], bool]:
    end_date = date.today()
    start_date = end_date - timedelta(days=days)
    for suffix in (".TW", ".TWO"):
        ticker = symbol if symbol.endswith((".TW", ".TWO")) else f"{symbol}{suffix}"
        try:
            df = yf.download(
                ticker,
                start=start_date,
                end=end_date + timedelta(days=1),
                progress=False,
                auto_adjust=False,
                threads=False,
            )
        except Exception:
            continue
        candles = _candles_from_yfinance_df(df)
        if len(candles) >= 60:
            return candles, False
    if allow_mock and data_source_settings.allow_mock_data():
        return _generate_mock_candles(symbol, days), True
    return [], False


def _candles_from_yfinance_df(df: pd.DataFrame) -> list[dict]:
    if df is None or df.empty:
        return []
    normalized = df.copy()
    if isinstance(normalized.columns, pd.MultiIndex):
        normalized.columns = normalized.columns.get_level_values(0)
    normalized = normalized.reset_index()
    candles = []
    for _, row in normalized.iterrows():
        try:
            close = float(row["Close"])
            candles.append({
                "time": row["Date"].date().isoformat() if hasattr(row["Date"], "date") else str(row["Date"])[:10],
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": close,
                "volume": int(row.get("Volume") or 0),
            })
        except Exception:
            continue
    return candles


async def get_tw_market_data(symbol: str) -> tuple[dict, bool]:
    """Return (market_dict, is_mock).

    market_dict keys: chart_data (list of CandlePoint dicts), current_price,
    price_change_percent, volume.
    """
    token = os.getenv("FINMIND_API_KEY")
    if not token:
        return _mock_market(symbol)

    end_date = date.today().strftime("%Y-%m-%d")
    start_date = (date.today() - timedelta(days=180)).strftime("%Y-%m-%d")

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                FINMIND_BASE,
                params={
                    "dataset": "TaiwanStockPrice",
                    "data_id": symbol,
                    "start_date": start_date,
                    "end_date": end_date,
                    "token": token,
                },
            )
            resp.raise_for_status()
            payload = resp.json()

        if payload.get("status") != 200 or not payload.get("data"):
            return _mock_market(symbol)

        rows = sorted(payload["data"], key=lambda r: r["date"])
        chart_data = [
            {
                "time": r["date"],
                "open": float(r["open"]),
                "high": float(r["max"]),
                "low": float(r["min"]),
                "close": float(r["close"]),
                "volume": int(r["Trading_Volume"]),
            }
            for r in rows
        ]

        if not chart_data:
            return _mock_market(symbol)

        last = chart_data[-1]
        prev_close = chart_data[-2]["close"] if len(chart_data) >= 2 else last["close"]
        price_change = (
            round((last["close"] - prev_close) / prev_close * 100, 2)
            if prev_close
            else 0.0
        )

        return {
            "chart_data": chart_data,
            "current_price": last["close"],
            "price_change_percent": price_change,
            "volume": last["volume"],
        }, False

    except Exception:
        return _mock_market(symbol)
