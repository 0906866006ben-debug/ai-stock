"""Historical data loading for Taiwan stock backtests."""

from __future__ import annotations

import os
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Iterable

import httpx
import pandas as pd

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - optional dependency guard
    load_dotenv = None

from backend.app.services.finmind_market import FINMIND_BASE, _generate_mock_candles
from ..contracts.input_contract import OHLCVBar, OHLCVSeries


class BacktestDataError(RuntimeError):
    """Raised when historical backtest data cannot be loaded."""


def load_symbol_series(
    symbol: str,
    *,
    start: date,
    end: date,
    warmup_bars: int,
    data_dir: Path | None = None,
    allow_mock: bool = False,
) -> OHLCVSeries:
    """Load OHLCV bars from CSV first, then FinMind, then optional mock."""

    fetch_start = start - timedelta(days=max(warmup_bars * 2, 260))
    if data_dir is not None:
        csv_path = _find_csv(data_dir, symbol)
        if csv_path is not None:
            bars = _bars_from_dataframe(symbol, pd.read_csv(csv_path), source=f"csv:{csv_path.name}")
            bars = _filter_bars(bars, fetch_start, end)
            if bars:
                return OHLCVSeries(symbol, bars)

    bars = _fetch_finmind_bars(symbol, fetch_start, end)
    if bars:
        return OHLCVSeries(symbol, bars)

    if allow_mock:
        days = max((end - fetch_start).days, warmup_bars + 80)
        candles = _generate_mock_candles(symbol, days)
        bars = _bars_from_candles(symbol, candles, source="mock")
        bars = _filter_bars(bars, fetch_start, end)
        if bars:
            return OHLCVSeries(symbol, bars)

    raise BacktestDataError(
        f"No historical data for {symbol}. Provide --data-dir, set FINMIND_API_KEY, or pass --allow-mock."
    )


def _find_csv(data_dir: Path, symbol: str) -> Path | None:
    candidates = [
        data_dir / f"{symbol}.csv",
        data_dir / f"{symbol}.CSV",
        data_dir / f"{symbol}_daily.csv",
        data_dir / f"{symbol}_ohlcv.csv",
    ]
    return next((path for path in candidates if path.exists()), None)


def _fetch_finmind_bars(symbol: str, start: date, end: date) -> list[OHLCVBar]:
    if load_dotenv is not None:
        load_dotenv("backend/.env")
    token = os.getenv("FINMIND_API_KEY")
    if not token:
        return []

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(
                FINMIND_BASE,
                params={
                    "dataset": "TaiwanStockPrice",
                    "data_id": symbol,
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat(),
                    "token": token,
                },
            )
            response.raise_for_status()
            payload = response.json()
    except Exception:
        return []

    if payload.get("status") != 200 or not payload.get("data"):
        return []
    rows = sorted(payload["data"], key=lambda row: row.get("date", ""))
    return _bars_from_rows(symbol, rows, source="finmind")


def _bars_from_dataframe(symbol: str, frame: pd.DataFrame, source: str) -> list[OHLCVBar]:
    records = frame.rename(columns={column: str(column).strip() for column in frame.columns}).to_dict("records")
    return _bars_from_rows(symbol, records, source=source)


def _bars_from_candles(symbol: str, candles: Iterable[dict], source: str) -> list[OHLCVBar]:
    rows = [
        {
            "date": item.get("time") or item.get("date"),
            "open": item.get("open"),
            "max": item.get("high"),
            "min": item.get("low"),
            "close": item.get("close"),
            "Trading_Volume": item.get("volume"),
            "Trading_money": item.get("turnover_value"),
        }
        for item in candles
    ]
    return _bars_from_rows(symbol, rows, source=source)


def _bars_from_rows(symbol: str, rows: Iterable[dict], source: str) -> list[OHLCVBar]:
    bars: list[OHLCVBar] = []
    previous_close: Decimal | None = None
    for raw in rows:
        try:
            day = date.fromisoformat(str(_pick(raw, "date", "time", "Date")))
            open_price = _decimal(_pick(raw, "open", "Open"))
            high = _decimal(_pick(raw, "max", "high", "High"))
            low = _decimal(_pick(raw, "min", "low", "Low"))
            close = _decimal(_pick(raw, "close", "Close"))
            volume = int(float(_pick(raw, "Trading_Volume", "volume", "Volume", default=0)))
            turnover_value = _pick(raw, "Trading_money", "turnover_value", "Turnover", default=None)
            turnover = _decimal(turnover_value) if turnover_value not in (None, "") else close * Decimal(volume)
        except Exception:
            continue

        bars.append(
            OHLCVBar(
                date=day,
                open=open_price,
                high=high,
                low=low,
                close=close,
                volume=volume,
                turnover_value=turnover,
                is_adjusted=True,
                data_source=source,
                previous_close=previous_close,
            )
        )
        previous_close = close
    return sorted(bars, key=lambda bar: bar.date)


def _pick(raw: dict, *keys: str, default=None):
    for key in keys:
        if key in raw and raw[key] == raw[key]:  # filters NaN
            return raw[key]
    return default


def _decimal(value: object) -> Decimal:
    return Decimal(str(value).replace(",", ""))


def _filter_bars(bars: list[OHLCVBar], start: date, end: date) -> list[OHLCVBar]:
    return [bar for bar in bars if start <= bar.date <= end]
