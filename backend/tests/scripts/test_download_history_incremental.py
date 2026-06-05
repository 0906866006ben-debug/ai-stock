from __future__ import annotations

from backend.app.services.backtest.historical_data_store import HistoricalDataStore
from backend.scripts.download_history import incremental_days_by_symbol, incremental_days_for_gap


def test_incremental_days_uses_latest_local_bar(tmp_path):
    store = HistoricalDataStore(tmp_path / "ohlcv.db")
    store.upsert_rows([
        {
            "stock_id": "2330",
            "date": "2026-05-30",
            "open": 100,
            "high": 101,
            "low": 99,
            "close": 100,
            "volume": 1_000,
            "turnover": 100_000,
        }
    ])

    days = incremental_days_for_gap(
        store,
        ["2330"],
        end_date="2026-06-01",
        min_days=10,
        buffer_days=3,
        max_days=1500,
    )

    assert days == 10


def test_incremental_days_expands_for_stale_or_missing_symbol(tmp_path):
    store = HistoricalDataStore(tmp_path / "ohlcv.db")
    store.upsert_rows([
        {
            "stock_id": "2330",
            "date": "2026-01-01",
            "open": 100,
            "high": 101,
            "low": 99,
            "close": 100,
            "volume": 1_000,
            "turnover": 100_000,
        }
    ])

    assert incremental_days_for_gap(store, ["2330"], end_date="2026-06-01", buffer_days=7) == 158
    assert incremental_days_for_gap(store, ["9999"], end_date="2026-06-01", max_days=777) == 777


def test_incremental_days_by_symbol_keeps_missing_symbol_isolated(tmp_path):
    store = HistoricalDataStore(tmp_path / "ohlcv.db")
    store.upsert_rows([
        {
            "stock_id": "2330",
            "date": "2026-05-30",
            "open": 100,
            "high": 101,
            "low": 99,
            "close": 100,
            "volume": 1_000,
            "turnover": 100_000,
        }
    ])

    days = incremental_days_by_symbol(
        store,
        ["2330", "9999"],
        end_date="2026-06-01",
        min_days=10,
        buffer_days=3,
        max_days=777,
    )

    assert days == {"2330": 10, "9999": 777}
    assert incremental_days_for_gap(store, ["2330", "9999"], end_date="2026-06-01", max_days=777) == 777
