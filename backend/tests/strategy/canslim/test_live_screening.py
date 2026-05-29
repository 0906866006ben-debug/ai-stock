from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient

from backend.app.models.screener_schemas import ScreeningResult
from backend.app.services.backtest.historical_data_store import HistoricalDataStore
from backend.app.services.backtest.pit_fundamentals_store import PitFundamentalsStore
from backend.app.services.strategy.canslim.screening import contains_forbidden_action_language
from backend.app.services.strategy.canslim.types import MarketFeatures


def _seed_ohlcv(store: HistoricalDataStore, symbol: str = "2330", days: int = 270) -> str:
    start = date(2025, 1, 1)
    rows = []
    for i in range(days):
        current = start + timedelta(days=i)
        close = 80 + i * 0.2
        rows.append(
            {
                "stock_id": symbol,
                "date": current.isoformat(),
                "open": close - 0.5,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": 2_000_000 + i * 1000,
                "turnover": close * (2_000_000 + i * 1000),
            }
        )
    store.upsert_rows(rows)
    return rows[-1]["date"]


def _seed_ohlcv_trend(store: HistoricalDataStore, symbol: str, *, start_close: float, step: float, days: int = 270) -> str:
    start = date(2025, 1, 1)
    rows = []
    for i in range(days):
        current = start + timedelta(days=i)
        close = max(1.0, start_close + i * step)
        rows.append(
            {
                "stock_id": symbol,
                "date": current.isoformat(),
                "open": close - 0.5,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": 2_000_000 + i * 1000,
                "turnover": close * (2_000_000 + i * 1000),
            }
        )
    store.upsert_rows(rows)
    return rows[-1]["date"]


def _seed_pit(store: PitFundamentalsStore, symbol: str = "2330") -> None:
    store.upsert_month_revenue(
        [
            {"stock_id": symbol, "date": "2025-07-01", "revenue": 100, "revenue_yoy": 0.20, "revenue_mom": 0.02, "raw_json": "{}"},
            {"stock_id": symbol, "date": "2025-08-01", "revenue": 120, "revenue_yoy": 0.32, "revenue_mom": 0.20, "raw_json": "{}"},
        ]
    )
    store.upsert_institutional(
        [
            {"stock_id": symbol, "date": f"2025-09-{day:02d}", "foreign_net": 1, "trust_net": 1, "dealer_net": 0, "raw_json": "{}"}
            for day in range(1, 7)
        ]
    )
    store.upsert_per([{"stock_id": symbol, "date": "2025-09-20", "per": 18, "pbr": 3, "dividend_yield": 1, "raw_json": "{}"}])
    store.upsert_financials(
        [
            {"stock_id": symbol, "period_end": "2022-12-31", "filing_date": "2023-03-31", "eps": 5, "roe": 0.16, "gross_margin": 0.45, "operating_margin": 0.28, "net_margin": 0.22, "raw_json": "{}"},
            {"stock_id": symbol, "period_end": "2023-12-31", "filing_date": "2024-03-31", "eps": 6, "roe": 0.17, "gross_margin": 0.46, "operating_margin": 0.29, "net_margin": 0.23, "raw_json": "{}"},
            {"stock_id": symbol, "period_end": "2024-12-31", "filing_date": "2025-03-31", "eps": 8, "roe": 0.20, "gross_margin": 0.48, "operating_margin": 0.31, "net_margin": 0.25, "raw_json": "{}"},
            {"stock_id": symbol, "period_end": "2025-06-30", "filing_date": "2025-08-15", "eps": 10, "roe": 0.22, "gross_margin": 0.50, "operating_margin": 0.34, "net_margin": 0.27, "raw_json": "{}"},
        ]
    )


def _seed_minimal_pit(store: PitFundamentalsStore, symbol: str) -> None:
    store.upsert_month_revenue(
        [{"stock_id": symbol, "date": "2025-08-01", "revenue": 100, "revenue_yoy": 0.2, "revenue_mom": 0.1, "raw_json": "{}"}]
    )


async def _fake_yahoo_news(symbol: str, company_name: str = "") -> list[dict]:
    return [
        {
            "title": "advanced packaging capacity update",
            "published_at": "2025-09-20",
            "source": "Test News",
            "url": "https://example.com/news",
        }
    ]


async def _fake_tw_news(symbol: str):
    return [], False


async def _async_fallback(detail: dict, metrics: dict, warnings: list[str], is_mock: bool):
    return detail, metrics, warnings, is_mock


def test_screen_symbol_seeded_stores_returns_all_pillars(tmp_path, monkeypatch):
    from backend.app.services.strategy.canslim import live_screening

    ohlcv = HistoricalDataStore(tmp_path / "ohlcv.db")
    pit = PitFundamentalsStore(tmp_path / "pit.db")
    as_of = _seed_ohlcv(ohlcv)
    _seed_pit(pit)

    monkeypatch.setattr(
        live_screening,
        "build_market_features",
        lambda *args, **kwargs: MarketFeatures(
            taiex_close=100,
            taiex_ma150=90,
            taiex_ma150_slope=0.1,
            tpex_close=100,
            tpex_ma150=90,
            tpex_ma150_slope=0.1,
            breadth_above_ma60_pct=0.8,
        ),
    )
    monkeypatch.setattr(live_screening, "get_tw_stock_news_yahoo", _fake_yahoo_news)

    import asyncio

    result = asyncio.run(live_screening.screen_symbol("2330", ohlcv_store=ohlcv, pit_store=pit))

    assert result.stock_id == "2330"
    assert result.as_of_date == as_of
    assert set(result.pillars) == {"C", "A", "N", "S", "L", "I", "M"}
    assert result.is_mock is False
    assert any("DATA STALE" in item for item in result.data_warnings)
    assert not contains_forbidden_action_language(result.model_dump())


def test_screen_symbol_computes_universe_rs_and_l_resolves(tmp_path, monkeypatch):
    from backend.app.services.strategy.canslim import live_screening

    live_screening.clear_universe_returns_cache()
    ohlcv = HistoricalDataStore(tmp_path / "ohlcv.db")
    pit = PitFundamentalsStore(tmp_path / "pit.db")
    _seed_ohlcv_trend(ohlcv, "2330", start_close=50, step=0.5)
    _seed_ohlcv_trend(ohlcv, "2454", start_close=100, step=0.0)
    _seed_ohlcv_trend(ohlcv, "2308", start_close=120, step=-0.1)
    _seed_pit(pit, "2330")
    _seed_minimal_pit(pit, "2454")
    _seed_minimal_pit(pit, "2308")

    monkeypatch.setattr(live_screening, "build_market_features", lambda *args, **kwargs: MarketFeatures())
    monkeypatch.setattr(live_screening, "get_tw_stock_news_yahoo", _fake_yahoo_news)
    monkeypatch.setattr(live_screening, "_live_fundamental_fallback", lambda symbol: _async_fallback({}, {}, [], False))

    import asyncio

    result = asyncio.run(live_screening.screen_symbol("2330", ohlcv_store=ohlcv, pit_store=pit))

    assert result.pillars["L"] in {"Pass", "Weak", "Fail"}
    assert result.pillars["L"] != "Insufficient_Data"


def test_market_features_receives_screenable_universe_for_breadth(tmp_path, monkeypatch):
    from backend.app.services.strategy.canslim import live_screening

    ohlcv = HistoricalDataStore(tmp_path / "ohlcv.db")
    pit = PitFundamentalsStore(tmp_path / "pit.db")
    _seed_ohlcv_trend(ohlcv, "2330", start_close=50, step=0.5)
    _seed_ohlcv_trend(ohlcv, "2454", start_close=80, step=0.2)
    _seed_ohlcv_trend(ohlcv, "9999", start_close=80, step=0.2)
    _seed_pit(pit, "2330")
    _seed_minimal_pit(pit, "2454")
    captured: dict[str, list[str]] = {}

    def fake_market(as_of_date: str, *, store, universe):
        captured["universe"] = list(universe)
        return MarketFeatures(taiex_close=100, taiex_ma150=90, taiex_ma150_slope=0.1, tpex_close=100, tpex_ma150=90, tpex_ma150_slope=0.1, breadth_above_ma60_pct=0.8)

    monkeypatch.setattr(live_screening, "build_market_features", fake_market)
    monkeypatch.setattr(live_screening, "get_tw_stock_news_yahoo", _fake_yahoo_news)

    import asyncio

    result = asyncio.run(live_screening.screen_symbol("2330", ohlcv_store=ohlcv, pit_store=pit))

    assert captured["universe"] == ["2330", "2454"]
    assert result.pillars["M"] != "Insufficient_Data"


def test_uncovered_symbol_keeps_l_but_warns_cai_without_mock(tmp_path, monkeypatch):
    from backend.app.services.strategy.canslim import live_screening

    live_screening.clear_universe_returns_cache()
    ohlcv = HistoricalDataStore(tmp_path / "ohlcv.db")
    pit = PitFundamentalsStore(tmp_path / "pit.db")
    _seed_ohlcv_trend(ohlcv, "3481", start_close=40, step=0.4)
    _seed_ohlcv_trend(ohlcv, "2330", start_close=50, step=0.1)
    _seed_minimal_pit(pit, "2330")

    monkeypatch.setattr(live_screening, "build_market_features", lambda *args, **kwargs: MarketFeatures())
    monkeypatch.setattr(live_screening, "get_tw_stock_news_yahoo", _fake_yahoo_news)

    import asyncio

    result = asyncio.run(live_screening.screen_symbol("3481", ohlcv_store=ohlcv, pit_store=pit))

    assert result.is_mock is False
    assert result.pillars["C"] == "Insufficient_Data"
    assert result.pillars["A"] == "Insufficient_Data"
    assert result.pillars["I"] == "Insufficient_Data"
    assert result.pillars["L"] != "Insufficient_Data"
    assert any("3481 has no PIT fundamentals coverage" in item for item in result.data_warnings)


def test_universe_returns_cache_reuses_same_asof_and_universe(tmp_path, monkeypatch):
    from backend.app.services.strategy.canslim import live_screening

    live_screening.clear_universe_returns_cache()
    ohlcv = HistoricalDataStore(tmp_path / "ohlcv.db")
    pit = PitFundamentalsStore(tmp_path / "pit.db")
    _seed_ohlcv_trend(ohlcv, "2330", start_close=50, step=0.5)
    _seed_ohlcv_trend(ohlcv, "2454", start_close=100, step=0.0)
    _seed_pit(pit, "2330")
    _seed_minimal_pit(pit, "2454")
    monkeypatch.setattr(live_screening, "build_market_features", lambda *args, **kwargs: MarketFeatures())
    monkeypatch.setattr(live_screening, "get_tw_stock_news_yahoo", _fake_yahoo_news)

    original = live_screening._compute_universe_returns
    calls = {"count": 0}

    def spy(*args, **kwargs):
        calls["count"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(live_screening, "_compute_universe_returns", spy)

    import asyncio

    asyncio.run(live_screening.screen_symbol("2330", ohlcv_store=ohlcv, pit_store=pit))
    asyncio.run(live_screening.screen_symbol("2330", ohlcv_store=ohlcv, pit_store=pit))

    assert calls["count"] == 2


def test_screen_symbol_missing_fundamentals_is_insufficient_not_crash(tmp_path, monkeypatch):
    from backend.app.services.strategy.canslim import live_screening

    ohlcv = HistoricalDataStore(tmp_path / "ohlcv.db")
    pit = PitFundamentalsStore(tmp_path / "pit.db")
    _seed_ohlcv(ohlcv)
    _seed_minimal_pit(pit, "2330")
    monkeypatch.setattr(live_screening, "build_market_features", lambda *args, **kwargs: MarketFeatures())
    monkeypatch.setattr(live_screening, "get_tw_stock_news_yahoo", _fake_yahoo_news)

    async def no_live_fields(symbol: str, as_of_date: str):
        return {}, {}, None, ["fundamental fallback unavailable"], True

    monkeypatch.setattr(live_screening, "_live_fundamental_fallback", no_live_fields)

    import asyncio

    result = asyncio.run(live_screening.screen_symbol("2330", ohlcv_store=ohlcv, pit_store=pit))

    assert result.pillars["C"] == "Insufficient_Data"
    assert result.pillars["A"] == "Insufficient_Data"
    assert result.is_mock is True
    assert any("fundamental fallback unavailable" in item for item in result.data_warnings)


def test_staleness_warning_fresh_date_has_no_warning(monkeypatch):
    from backend.app.services.strategy.canslim import live_screening

    stale_warnings: list[str] = []
    assert live_screening._append_staleness_warning("2024-01-02", stale_warnings) is True
    assert any("DATA STALE" in item for item in stale_warnings)

    fresh_warnings: list[str] = []
    assert live_screening._append_staleness_warning(date.today().isoformat(), fresh_warnings) is False
    assert not any("DATA STALE" in item for item in fresh_warnings)


def test_single_point_live_fallback_does_not_synthesize_series(tmp_path, monkeypatch):
    from backend.app.services.strategy.canslim import live_screening

    ohlcv = HistoricalDataStore(tmp_path / "ohlcv.db")
    pit = PitFundamentalsStore(tmp_path / "pit.db")
    _seed_ohlcv(ohlcv)
    _seed_minimal_pit(pit, "2330")

    async def one_point_detail(symbol: str) -> dict:
        return {
            "revenue_summary": {"yoy_pct": 30.0},
            "institutional_summary": {
                "foreign_net_5d": 1000,
                "trust_net_5d": 0,
                "dealer_net_5d": 0,
            },
        }

    async def empty_metrics(symbol: str) -> dict:
        return {}

    monkeypatch.setattr(live_screening, "get_tw_detail", one_point_detail)
    monkeypatch.setattr(live_screening, "fetch_real_metrics", empty_metrics)
    monkeypatch.setattr(live_screening, "build_market_features", lambda *args, **kwargs: MarketFeatures())
    monkeypatch.setattr(live_screening, "get_tw_stock_news_yahoo", _fake_yahoo_news)

    import asyncio

    result = asyncio.run(live_screening.screen_symbol("2330", ohlcv_store=ohlcv, pit_store=pit))

    assert result.pillars["C"] == "Insufficient_Data"
    assert result.pillars["I"] == "Insufficient_Data"
    assert any("multi-period series unavailable" in item for item in result.data_warnings)
    assert any("5-day series unavailable" in item for item in result.data_warnings)


def test_as_of_mismatch_warning_when_live_fallback_blends_with_stale_price(tmp_path, monkeypatch):
    from backend.app.services.strategy.canslim import live_screening

    ohlcv = HistoricalDataStore(tmp_path / "ohlcv.db")
    pit = PitFundamentalsStore(tmp_path / "pit.db")
    _seed_ohlcv(ohlcv)
    _seed_minimal_pit(pit, "2330")

    async def fallback(symbol: str, as_of_date: str):
        return {"month_revenue_yoy": [0.1, 0.2, 0.3]}, {"quarterly_eps_yoy": 0.3}, None, [], False

    monkeypatch.setattr(live_screening, "_live_fundamental_fallback", fallback)
    monkeypatch.setattr(live_screening, "build_market_features", lambda *args, **kwargs: MarketFeatures())
    monkeypatch.setattr(live_screening, "get_tw_stock_news_yahoo", _fake_yahoo_news)

    import asyncio

    result = asyncio.run(live_screening.screen_symbol("2330", ohlcv_store=ohlcv, pit_store=pit))

    assert any("as-of mismatch" in item for item in result.data_warnings)
    assert result.is_mock is False


def test_tw_screen_endpoint_returns_screening_result_without_action_language(monkeypatch):
    from backend.app import main

    async def fake_screen_symbol(symbol: str, as_of_date: str | None = None) -> ScreeningResult:
        return ScreeningResult(
            stock_id=symbol,
            as_of_date=as_of_date or "2026-01-02",
            is_mock=True,
            candidate_grade="C",
            canslim_match="2/7",
            pillars={pillar: "Insufficient_Data" for pillar in ("C", "A", "N", "S", "L", "I", "M")},
            market_regime="unknown",
            interpretation="CANSLIM condition data is incomplete.",
            evidence=[],
            data_warnings=["mock path"],
            needs_manual_review=["C"],
            action_type="Manual Review Required",
        )

    monkeypatch.setattr(main, "screen_symbol", fake_screen_symbol)
    client = TestClient(main.app)

    response = client.get("/tw/screen", params={"symbol": "2330", "as_of_date": "2026-01-02"})

    assert response.status_code == 200
    body = response.json()
    assert body["stock_id"] == "2330"
    assert body["is_mock"] is True
    assert set(body["pillars"]) == {"C", "A", "N", "S", "L", "I", "M"}
    assert not contains_forbidden_action_language(body)


def test_analyze_tw_screening_result_gated_off(monkeypatch):
    from backend.app.main import app

    monkeypatch.delenv("FINMIND_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    client = TestClient(app)

    response = client.get("/analyze/tw", params={"symbol": "2330"})

    assert response.status_code == 200
    assert response.json()["screening_result"] is None
