from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Protocol

from .schemas import UniverseSnapshotResponse, UniverseSymbol


def _filter_value(filters: list[dict[str, Any]], filter_type: str, key: str) -> str | None:
    for item in filters:
        if item.get("filterType") == filter_type:
            value = item.get(key)
            return str(value) if value is not None else None
    return None


class UniverseBuilder:
    def __init__(self, client: "ExchangeInfoClient" | None = None) -> None:
        self.client = client or BinanceExchangeInfoClient()

    def fetch_current(self) -> UniverseSnapshotResponse:
        payload = self.client.get_json("/fapi/v1/exchangeInfo")
        symbols: list[UniverseSymbol] = []
        for item in payload.get("symbols", []):
            if item.get("contractType") != "PERPETUAL" or item.get("quoteAsset") != "USDT":
                continue
            filters = list(item.get("filters") or [])
            symbols.append(
                UniverseSymbol(
                    symbol=str(item.get("symbol") or ""),
                    pair=item.get("pair"),
                    base_asset=str(item.get("baseAsset") or ""),
                    quote_asset=str(item.get("quoteAsset") or ""),
                    contract_type=str(item.get("contractType") or ""),
                    status=str(item.get("status") or "UNKNOWN"),
                    onboard_date=item.get("onboardDate"),
                    delivery_date=item.get("deliveryDate"),
                    tick_size=_filter_value(filters, "PRICE_FILTER", "tickSize"),
                    step_size=_filter_value(filters, "LOT_SIZE", "stepSize"),
                    minimum_quantity=_filter_value(filters, "LOT_SIZE", "minQty"),
                    minimum_notional=_filter_value(filters, "MIN_NOTIONAL", "notional"),
                    funding_interval_hours=None,
                )
            )
        symbols.sort(key=lambda item: item.symbol)
        observed_at = datetime.now(timezone.utc)
        return UniverseSnapshotResponse(
            snapshot_id=f"binance:{int(observed_at.timestamp())}",
            observed_at=observed_at,
            source="BINANCE_FAPI_EXCHANGE_INFO",
            symbols=symbols,
            historical_completeness="CURRENT_SNAPSHOT_ONLY",
            warnings=[
                "This is a current exchange snapshot, not a complete historical universe; it must not be backfilled into past tests."
            ],
        )


class ExchangeInfoClient(Protocol):
    def get_json(self, path: str) -> Any: ...


class BinanceExchangeInfoClient:
    def __init__(self, base_url: str = "https://fapi.binance.com", timeout: int = 20, max_retries: int = 4) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries

    def get_json(self, path: str) -> Any:
        last_error = ""
        for attempt in range(self.max_retries):
            request = urllib.request.Request(
                self.base_url + path,
                headers={"User-Agent": "ai-stock-research/0.1"},
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return json.loads(response.read())
            except (urllib.error.HTTPError, urllib.error.URLError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                retryable = not isinstance(exc, urllib.error.HTTPError) or exc.code in {418, 429, 500, 502, 503, 504}
                if not retryable or attempt == self.max_retries - 1:
                    break
                time.sleep(min(8.0, 1.5 * (attempt + 1)))
        raise RuntimeError(last_error or "Binance exchange-info request failed")
