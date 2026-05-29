from __future__ import annotations

from backend.app.models.schemas import TaiwanStockAnalysisResponse


def _minimal_kwargs():
    return dict(
        symbol="2330", company_name="台積電", market_type="TWSE",
        current_price=900.0, price_change_percent=1.2, volume=10000,
        trend="中立", confidence=0.5, summary="s", risks=[], catalysts=[],
        recommendation="r", chart_data=[], data_source="live",
        analysis_source="ai", analyzed_at="2024-06-28T00:00:00Z",
    )


def test_tw_response_works_without_canslim_full():
    resp = TaiwanStockAnalysisResponse(**_minimal_kwargs())
    assert resp.canslim_full is None
    assert resp.screening_result is None
    assert resp.canslim_summary is None


def test_existing_noncanslim_fields_preserved_in_dump():
    resp = TaiwanStockAnalysisResponse(**_minimal_kwargs())
    d = resp.model_dump()
    for field in ("symbol", "company_name", "current_price", "trend", "recommendation",
                  "data_source", "analysis_source", "disclaimer"):
        assert field in d
    # new field is additive + nullable
    assert d["canslim_full"] is None
    # an old client ignoring unknown fields still sees the contract it relied on
    assert d["disclaimer"] == "本分析僅供參考，不構成投資建議。"


def test_full_result_attaches_as_canslim_full():
    from backend.app.models.screener_schemas import ScreeningResult
    from backend.app.services.strategy.canslim.canslim_output import build_full_result
    sr = ScreeningResult(
        stock_id="2330", as_of_date="2024-06-28", candidate_grade="A",
        canslim_match="7/7", pillars={p: "Pass" for p in "CANSLIM"},
        market_regime="risk_on", interpretation="x", action_type="Watchlist Candidate",
    )
    full = build_full_result(sr)
    resp = TaiwanStockAnalysisResponse(**{**_minimal_kwargs(), "canslim_full": full})
    assert resp.canslim_full is not None
    assert resp.canslim_full.grade == "A"
