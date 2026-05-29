from __future__ import annotations

from pathlib import Path

import pandas as pd

from backend.app.services.backtest.historical_data_store import HistoricalDataStore
from backend.app.services.strategy.canslim.pit_universe import get_universe_as_of
from backend.app.services.strategy.canslim.universe_source import (
    parse_all_universe_symbols,
    parse_delisted_symbols,
    parse_tech_universe_symbols,
)


def test_universe_as_of_uses_only_current_liquidity(tmp_path: Path):
    store = _store(tmp_path)

    early = get_universe_as_of("2024-03-01", store, turnover_floor=30_000_000, candidate_symbols=["LIQ", "LATE"])
    later = get_universe_as_of("2024-05-01", store, turnover_floor=30_000_000, candidate_symbols=["LIQ", "LATE"])

    assert early == ["LIQ"]
    assert later == ["LATE", "LIQ"]


def test_insufficient_history_is_excluded(tmp_path: Path):
    store = HistoricalDataStore(tmp_path / "ohlcv.db")
    _insert_rows(store, "SHORT", "2024-01-01", 30, 50_000_000)

    result = get_universe_as_of("2024-02-15", store, turnover_floor=30_000_000, candidate_symbols=["SHORT"])

    assert result == []


def test_membership_changes_across_dates_as_liquidity_changes(tmp_path: Path):
    store = _store(tmp_path)

    before = get_universe_as_of("2024-03-01", store, turnover_floor=30_000_000, candidate_symbols=["FADING"])
    after = get_universe_as_of("2024-05-01", store, turnover_floor=30_000_000, candidate_symbols=["FADING"])

    assert before == ["FADING"]
    assert after == []


def test_parse_tech_universe_symbols_filters_categories_and_etfs():
    rows = [
        {"stock_id": "2330", "type": "twse", "industry_category": "半導體業"},
        {"stock_id": "3037", "type": "twse", "industry_category": "電腦及週邊設備業"},
        {"stock_id": "2412", "type": "twse", "industry_category": "通信網路業"},
        {"stock_id": "2882", "type": "twse", "industry_category": "金融保險業"},
        {"stock_id": "0050", "type": "ETF", "industry_category": "ETF"},
        {"stock_id": "12345", "type": "twse", "industry_category": "半導體業"},
    ]

    assert parse_tech_universe_symbols(rows) == ["2330", "2412", "3037"]


def test_parse_all_universe_symbols_includes_every_industry_excludes_etf():
    rows = [
        {"stock_id": "2330", "type": "twse", "industry_category": "半導體業"},
        {"stock_id": "2882", "type": "twse", "industry_category": "金融保險業"},
        {"stock_id": "2603", "type": "twse", "industry_category": "航運業"},
        {"stock_id": "1301", "type": "twse", "industry_category": "塑膠工業"},
        {"stock_id": "0050", "type": "ETF", "industry_category": "ETF"},
        {"stock_id": "12345", "type": "twse", "industry_category": "金融保險業"},
    ]
    # all common stocks across industries, ETF excluded by default
    assert parse_all_universe_symbols(rows) == ["1301", "2330", "2603", "2882"]
    # ETFs kept when requested (for price-only backfills)
    assert "0050" in parse_all_universe_symbols(rows, include_etf=True)


def test_staleness_guard_drops_delisted_after_last_bar(tmp_path: Path):
    # A delisted name: liquid bars that stop on 2024-03-10 (then no more trading).
    store = HistoricalDataStore(tmp_path / "ohlcv.db")
    _insert_rows(store, "GONE", "2024-01-01", 70, 70_000_000)  # ends ~2024-03-10

    # On its last trading day it is still a member.
    on_date = get_universe_as_of(
        "2024-03-10", store, turnover_floor=30_000_000,
        candidate_symbols=["GONE"], max_staleness_days=15,
    )
    # Two months later, its last bar is stale → it leaves the universe.
    later = get_universe_as_of(
        "2024-05-10", store, turnover_floor=30_000_000,
        candidate_symbols=["GONE"], max_staleness_days=15,
    )
    assert on_date == ["GONE"]
    assert later == []


def test_staleness_guard_none_is_no_op(tmp_path: Path):
    store = HistoricalDataStore(tmp_path / "ohlcv.db")
    _insert_rows(store, "GONE", "2024-01-01", 70, 70_000_000)
    # Without the guard, a stale last bar still counts (legacy behavior preserved).
    later = get_universe_as_of(
        "2024-05-10", store, turnover_floor=30_000_000, candidate_symbols=["GONE"],
    )
    assert later == ["GONE"]


def test_parse_delisted_symbols_keeps_common_stock_codes():
    rows = [
        {"stock_id": "2349", "date": "2018-06-01", "stock_name": "錸德"},
        {"stock_id": "0050", "date": "2019-01-01", "stock_name": "ETF"},  # ETF -> dropped
        {"stock_id": "1234", "date": "2017-01-01"},
        {"stock_id": "12345", "date": "2017-01-01"},  # not 4-digit -> dropped
    ]
    assert parse_delisted_symbols(rows) == ["1234", "2349"]


def _store(tmp_path: Path) -> HistoricalDataStore:
    store = HistoricalDataStore(tmp_path / "ohlcv.db")
    _insert_rows(store, "LIQ", "2024-01-01", 120, 60_000_000)
    _insert_rows(store, "LATE", "2024-01-01", 70, 5_000_000)
    _insert_rows(store, "LATE", "2024-03-11", 60, 70_000_000)
    _insert_rows(store, "FADING", "2024-01-01", 70, 70_000_000)
    _insert_rows(store, "FADING", "2024-03-11", 60, 5_000_000)
    return store


def _insert_rows(store: HistoricalDataStore, stock_id: str, start_date: str, days: int, turnover: float) -> None:
    start = pd.Timestamp(start_date)
    rows = []
    for idx in range(days):
        date = (start + pd.Timedelta(days=idx)).strftime("%Y-%m-%d")
        close = 100.0 + idx * 0.1
        rows.append(
            {
                "stock_id": stock_id,
                "date": date,
                "open": close,
                "high": close * 1.01,
                "low": close * 0.99,
                "close": close,
                "volume": int(turnover / close),
                "turnover": turnover,
            }
        )
    store.upsert_rows(rows)
