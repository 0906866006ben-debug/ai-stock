from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient

from backend.app.models.screener_schemas import CandidateMetrics, CandidateScores
from backend.app.services.backtest.historical_data_store import HistoricalDataStore
from backend.app.services.strategy.canslim.observer import observe
from backend.app.services.strategy.canslim.types import MarketFeatures


def test_analyze_tw_canslim_summary_none_when_flag_off(monkeypatch):
    from backend.app.main import app

    monkeypatch.delenv("FINMIND_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    client = TestClient(app)

    response = client.get("/analyze/tw", params={"symbol": "2330"})

    assert response.status_code == 200
    body = response.json()
    assert body["canslim_summary"] is None


def test_analyze_tw_canslim_summary_populates_when_enabled(monkeypatch):
    from backend.app.main import app

    monkeypatch.delenv("FINMIND_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    client = TestClient(app)

    response = client.get("/analyze/tw", params={"symbol": "2330", "include_canslim": True})

    assert response.status_code == 200
    summary = response.json()["canslim_summary"]
    assert summary is not None
    assert set(summary["grades"]) == {"short_term", "swing_term", "long_term"}
    assert all(grade in {"S", "A", "B", "C"} for grade in summary["grades"].values())
    assert set(summary["hard_blocked"]) == {"short_term", "swing_term", "long_term"}


def test_candidate_optional_canslim_fields_default_none():
    scores = CandidateScores(
        liquidity_score=1,
        price_position_score=2,
        base_compression_score=3,
        volume_score=4,
        ema_convergence_score=5,
        relative_strength_score=6,
    )
    metrics = CandidateMetrics(
        return_60d=0.1,
        return_20d=0.05,
        return_60_to_20=0.02,
        return_5d=0.01,
        avg_volume_20_lots=1000,
        avg_turnover_20=50_000_000,
        base_high=100,
        base_low=90,
        base_range_pct=0.1,
        volume_contraction_ratio=0.8,
        volume_recovery_ratio_5d=1.2,
        volume_today_ratio_20=1.5,
        ema_spread=0.02,
        ema5_slope=0.01,
        ema10_slope=0.01,
        ema20_slope=0.01,
        relative_strength_20d=None,
        relative_strength_60d=None,
        close_distance_from_ema20=0.03,
    )

    assert scores.canslim_signal is None
    assert scores.canslim_risk is None
    assert scores.canslim_confidence is None
    assert metrics.canslim_grade is None
    assert metrics.canslim_signal is None
    assert metrics.canslim_hard_blocked is None


def test_frequency_sanity_synthetic_multistock_has_nonzero_grade_spread(tmp_path):
    store = _multi_stock_store(tmp_path)
    market = MarketFeatures(
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
    distribution: dict[str, int] = {}
    blocked_count = 0
    for symbol, fin_metrics, detail, returns in [
        ("1001", _strong_fin(), _strong_detail(), 0.8),
        ("1002", _weak_fin(), _weak_detail(), 0.2),
        ("1003", _strong_fin(), _weak_detail(), 0.5),
    ]:
        cards = observe(
            symbol,
            "2024-09-16",
            store=store,
            market=market,
            fin_metrics=fin_metrics,
            detail=detail,
            universe_returns_60d={"1001": 0.8, "1002": 0.2, "1003": 0.5},
            universe_returns_252d={"1001": 0.8, "1002": 0.2, "1003": 0.5},
            event_window_active=False,
            eps_filing_date="2024-09-01",
        )
        for card in cards.values():
            grade = str(card.scores["grade"])
            distribution[grade] = distribution.get(grade, 0) + 1
            blocked_count += int(bool(card.scores["hard_blocked"]))

    assert sum(distribution.values()) == 9
    assert any(grade in distribution for grade in ("S", "A", "B"))
    assert distribution.get("C", 0) > 0
    assert blocked_count < 9


def _multi_stock_store(tmp_path) -> HistoricalDataStore:
    store = HistoricalDataStore(tmp_path / "phase_h.db")
    start = date(2024, 1, 1)
    rows = []
    for symbol, slope, turnover in [("1001", 0.20, 80_000_000), ("1002", 0.02, 35_000_000), ("1003", 0.12, 55_000_000)]:
        for idx in range(260):
            close = 100 + idx * slope
            volume = 1200.0
            if idx == 259 and symbol == "1001":
                close += 18
                volume = 3000.0
            rows.append(
                {
                    "stock_id": symbol,
                    "date": (start + timedelta(days=idx)).isoformat(),
                    "open": close - 0.2,
                    "high": close + 0.5,
                    "low": close - 0.5,
                    "close": close,
                    "volume": volume,
                    "turnover": turnover,
                }
            )
    store.upsert_rows(rows)
    return store


def _strong_fin():
    return {
        "eps_yoy": 0.35,  # fraction contract (+35%)
        "annual_eps": [10.0, 12.0, 16.0],
        "roe": 20.0,
        "op_margin_last4": [20.0, 21.0, 22.0, 23.0],
        "pe_ttm": 30.0,
    }


def _weak_fin():
    return {
        "eps_yoy": 0.05,  # fraction contract (+5%)
        "annual_eps": [10.0, 10.0, 10.0],
        "roe": 5.0,
        "op_margin_last4": [20.0, 19.0, 18.0, 17.0],
        "pe_ttm": 45.0,
    }


def _strong_detail():
    return {
        "month_revenue_yoy": [0.18, 0.22, 0.30],
        "foreign_net_5": [1, 2, 30, 30, 30],
        "trust_net_5": [1, 2, 3, 4, 5],
        "dealer_net_5": [0, 0, 0, 0, 0],
    }


def _weak_detail():
    return {
        "month_revenue_yoy": [0.01, 0.01, 0.02],
        "foreign_net_5": [-1, -1, -1, -1, -1],
        "trust_net_5": [-1, -1, -1, -1, -1],
        "dealer_net_5": [0, 0, 0, 0, 0],
    }
