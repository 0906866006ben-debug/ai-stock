from __future__ import annotations

from pathlib import Path

from backend.app.services.backtest.historical_data_store import HistoricalDataStore
from backend.app.services.backtest.pit_fundamentals_store import PitFundamentalsStore
from backend.app.services.strategy.canslim.features import build_features
from backend.app.services.strategy.canslim.observer import observe
from backend.app.services.strategy.canslim.pit_inputs import build_pit_inputs
from backend.app.services.strategy.canslim.types import MarketFeatures
from backend.app.services.strategy.canslim.walk_forward import run_real_data_walk_forward

AS_OF = "2024-09-16"


def test_build_pit_inputs_emits_observe_compatible_shapes(tmp_path: Path):
    ohlcv = _ohlcv_store(tmp_path)
    pit = _pit_store(tmp_path)

    detail, fin_metrics, eps_filing_date = build_pit_inputs("2330", AS_OF, pit)
    cards = observe(
        "2330",
        AS_OF,
        store=ohlcv,
        market=_market(),
        fin_metrics=fin_metrics,
        detail=detail,
        universe_returns_60d={"2330": 0.8, "2454": 0.1},
        universe_returns_252d={"2330": 0.8, "2454": 0.1},
        event_window_active=False,
        eps_filing_date=eps_filing_date,
    )

    assert detail["month_revenue_yoy"][-1] == 0.30
    assert detail["foreign_net_5"][-1] == {"date": "2024-09-16", "net": 100.0}
    assert fin_metrics["quarterly_eps_yoy"] == 0.5
    assert fin_metrics["annual_eps"][-1] > fin_metrics["annual_eps"][0]
    assert fin_metrics["pe_ttm"] == 18.0
    assert eps_filing_date == "2024-08-14"
    assert set(cards) == {"short_term", "swing_term", "long_term"}
    assert all(card.scores["grade"] in {"S", "A", "B", "C"} for card in cards.values())


def test_future_filed_financials_are_excluded_from_fin_metrics(tmp_path: Path):
    pit = _pit_store(tmp_path)
    pit.upsert_financials(
        [
            {
                "stock_id": "2330",
                "period_end": "2024-09-30",
                "filing_date": "2024-11-14",
                "eps": 99.0,
                "roe": 99.0,
                "operating_margin": 99.0,
            }
        ]
    )

    _detail, fin_metrics, eps_filing_date = build_pit_inputs("2330", AS_OF, pit)

    assert fin_metrics["quarterly_eps_yoy"] == 0.5
    assert fin_metrics["roe"] != 99.0
    assert eps_filing_date == "2024-08-14"


def test_institutional_list_of_dicts_uses_build_features_t_plus_one_lag(tmp_path: Path):
    ohlcv = _ohlcv_store(tmp_path)
    pit = _pit_store(tmp_path)
    detail, fin_metrics, eps_filing_date = build_pit_inputs("2330", AS_OF, pit)

    features = build_features(
        "2330",
        AS_OF,
        ohlcv,
        fin_metrics=fin_metrics,
        detail=detail,
        universe_returns_60d={"2330": 0.8, "2454": 0.1},
        universe_returns_252d={"2330": 0.8, "2454": 0.1},
        event_window_active=False,
        eps_filing_date=eps_filing_date,
    )

    assert detail["foreign_net_5"][-1]["date"] == AS_OF
    assert features.foreign_net_5[-1] == 80.0
    assert 100.0 not in features.foreign_net_5


def test_empty_pit_tables_do_not_fabricate_and_lower_confidence(tmp_path: Path):
    ohlcv = _ohlcv_store(tmp_path)
    pit = PitFundamentalsStore(tmp_path / "empty_pit.db")

    detail, fin_metrics, eps_filing_date = build_pit_inputs("2330", AS_OF, pit)
    cards = observe(
        "2330",
        AS_OF,
        store=ohlcv,
        market=_market(),
        fin_metrics=fin_metrics,
        detail=detail,
        universe_returns_60d={"2330": 0.8, "2454": 0.1},
        universe_returns_252d={"2330": 0.8, "2454": 0.1},
        event_window_active=False,
        eps_filing_date=eps_filing_date,
    )

    assert detail == {}
    assert fin_metrics == {}
    assert eps_filing_date is None
    assert cards["swing_term"].scores["confidence"] < 50
    assert cards["swing_term"].data_warnings


def test_single_stock_single_day_real_path_sanity(tmp_path: Path):
    ohlcv = _ohlcv_store(tmp_path)
    pit = _pit_store(tmp_path)

    report = run_real_data_walk_forward(
        run_id="j2_single_day",
        ohlcv_db_path=ohlcv.db_path,
        pit_db_path=pit.db_path,
        stock_universe=["2330"],
        windows=[(AS_OF, AS_OF, AS_OF, AS_OF)],
        params={
            "backtest.canslim.min_entry_grade": "B",
            "backtest.canslim.max_hold_days": 30,
            "scoring.grades.A_signal_min": 55,
            "scoring.grades.B_signal_min": 35,
        },
        output_dir=tmp_path / "artifacts",
        min_trades=1,
        market=_market(),
    )

    assert Path(report.artifact_json).exists()
    assert len(report.windows) == 1
    assert report.windows[0].grade_distribution
    assert 0 <= report.windows[0].oos_metrics["win_rate"] <= 1


def _ohlcv_store(tmp_path: Path) -> HistoricalDataStore:
    store = HistoricalDataStore(tmp_path / "ohlcv.db")
    rows = []
    start = __import__("pandas").Timestamp("2024-01-01")
    for idx in range(300):
        date = (start + __import__("pandas").Timedelta(days=idx)).strftime("%Y-%m-%d")
        close = 100.0 + idx * 0.15
        if date == AS_OF:
            close += 10.0
        if date > AS_OF:
            close += 10.0 + (idx - 259) * 0.5
        rows.append(
            {
                "stock_id": "2330",
                "date": date,
                "open": close,
                "high": close * 1.01,
                "low": close * 0.99,
                "close": close,
                "volume": 2600 if date == AS_OF else 1200,
                "turnover": 80_000_000,
            }
        )
    store.upsert_rows(rows)
    return store


def _pit_store(tmp_path: Path) -> PitFundamentalsStore:
    store = PitFundamentalsStore(tmp_path / "pit.db")
    store.upsert_month_revenue(
        [
            {"stock_id": "2330", "date": "2023-07-31", "revenue": 100.0},
            {"stock_id": "2330", "date": "2023-08-31", "revenue": 110.0},
            {"stock_id": "2330", "date": "2024-07-31", "revenue": 125.0, "revenue_yoy": 0.25},
            {"stock_id": "2330", "date": "2024-08-31", "revenue": 143.0, "revenue_yoy": 0.30},
        ]
    )
    store.upsert_institutional(
        [
            {"stock_id": "2330", "date": "2024-09-13", "foreign_net": 60.0, "trust_net": 20.0, "dealer_net": 1.0},
            {"stock_id": "2330", "date": "2024-09-15", "foreign_net": 80.0, "trust_net": 30.0, "dealer_net": 1.0},
            {"stock_id": "2330", "date": "2024-09-16", "foreign_net": 100.0, "trust_net": 40.0, "dealer_net": 1.0},
        ]
    )
    store.upsert_per([{"stock_id": "2330", "date": AS_OF, "per": 18.0, "pbr": 3.0, "dividend_yield": 2.0}])
    financial_rows = []
    for year, base_eps in [(2021, 1.0), (2022, 1.2), (2023, 1.5)]:
        for period, filing in [
            ("03-31", "05-15"),
            ("06-30", "08-14"),
            ("09-30", "11-14"),
            ("12-31", "03-31"),
        ]:
            filing_year = year + 1 if period == "12-31" else year
            financial_rows.append(
                {
                    "stock_id": "2330",
                    "period_end": f"{year}-{period}",
                    "filing_date": f"{filing_year}-{filing}",
                    "eps": base_eps,
                    "roe": 18.0,
                    "gross_margin": 50.0,
                    "operating_margin": 35.0,
                    "net_margin": 30.0,
                }
            )
    financial_rows.extend(
        [
            {
                "stock_id": "2330",
                "period_end": "2024-03-31",
                "filing_date": "2024-05-15",
                "eps": 2.0,
                "roe": 20.0,
                "gross_margin": 52.0,
                "operating_margin": 36.0,
                "net_margin": 31.0,
            },
            {
                "stock_id": "2330",
                "period_end": "2024-06-30",
                "filing_date": "2024-08-14",
                "eps": 2.25,
                "roe": 20.0,
                "gross_margin": 52.0,
                "operating_margin": 37.0,
                "net_margin": 31.0,
            },
        ]
    )
    store.upsert_financials(financial_rows)
    return store


def _market() -> MarketFeatures:
    return MarketFeatures(
        taiex_close=20_000,
        taiex_ma150=19_000,
        taiex_ma150_slope=0.01,
        tpex_close=250,
        tpex_ma150=240,
        tpex_ma150_slope=0.01,
        breadth_above_ma60_pct=0.7,
        sox_above_ma60=True,
        nasdaq_above_ma60=True,
    )
