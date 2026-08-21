from __future__ import annotations

from backend.app.research_platform.universe import UniverseBuilder


class FakeClient:
    def get_json(self, path: str):
        assert path == "/fapi/v1/exchangeInfo"
        return {
            "symbols": [
                {
                    "symbol": "BTCUSDT",
                    "pair": "BTCUSDT",
                    "baseAsset": "BTC",
                    "quoteAsset": "USDT",
                    "contractType": "PERPETUAL",
                    "status": "TRADING",
                    "onboardDate": 1,
                    "deliveryDate": 2,
                    "filters": [
                        {"filterType": "PRICE_FILTER", "tickSize": "0.10"},
                        {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001"},
                        {"filterType": "MIN_NOTIONAL", "notional": "100"},
                    ],
                },
                {
                    "symbol": "ETHUSDC",
                    "baseAsset": "ETH",
                    "quoteAsset": "USDC",
                    "contractType": "PERPETUAL",
                    "status": "TRADING",
                    "filters": [],
                },
                {
                    "symbol": "BTCUSDT_260925",
                    "baseAsset": "BTC",
                    "quoteAsset": "USDT",
                    "contractType": "CURRENT_QUARTER",
                    "status": "TRADING",
                    "filters": [],
                },
            ]
        }


def test_universe_builder_keeps_only_usdt_perpetuals_and_marks_history_limit() -> None:
    snapshot = UniverseBuilder(client=FakeClient()).fetch_current()

    assert [item.symbol for item in snapshot.symbols] == ["BTCUSDT"]
    assert snapshot.symbols[0].tick_size == "0.10"
    assert snapshot.symbols[0].minimum_notional == "100"
    assert snapshot.historical_completeness == "CURRENT_SNAPSHOT_ONLY"
    assert snapshot.warnings

