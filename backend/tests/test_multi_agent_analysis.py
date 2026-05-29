import pytest
from fastapi.testclient import TestClient

from backend.app.models.schemas import AgentEvidencePack, ClaudeFinalReview, GeminiStructuredInsight
from backend.app.services.multi_agent_analysis import run_multi_agent_analysis


def _sample_packs() -> list[AgentEvidencePack]:
    return [
        AgentEvidencePack(
            id="price",
            label="價格量能",
            source="FinMind",
            status="available",
            latest_date="2026-05-22",
            summary="最新收盤 100.00，單日變動 1.00%；近 20 日量比 1.20x。",
        ),
        AgentEvidencePack(
            id="revenue",
            label="月營收",
            source="FinMind",
            status="available",
            summary="最新月營收 1,000，年增 12.00%，月增 3.00%。",
        ),
        AgentEvidencePack(
            id="valuation",
            label="估值",
            source="FinMind",
            status="missing",
            summary="估值資料不足。",
            warnings=["valuation_missing"],
        ),
    ]


@pytest.mark.asyncio
async def test_multi_agent_analysis_falls_back_without_model_keys(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    async def fake_evidence(symbol: str):
        return _sample_packs(), ["valuation_missing"], False

    monkeypatch.setattr(
        "backend.app.services.multi_agent_analysis.build_finmind_evidence",
        fake_evidence,
    )

    response = await run_multi_agent_analysis("2330")

    assert response.symbol == "2330"
    assert response.is_mock is False
    assert response.data_warnings == ["valuation_missing"]
    assert response.analysis.agents[0].status == "completed"
    assert response.analysis.agents[1].status == "fallback"
    assert response.analysis.agents[2].status == "fallback"
    assert response.analysis.gemini_structured.key_points
    assert response.analysis.claude_final.status in {"Neutral", "Insufficient_Data"}


@pytest.mark.asyncio
async def test_multi_agent_pipeline_can_report_real_agent_completion(monkeypatch):
    async def fake_evidence(symbol: str):
        return _sample_packs(), [], False

    async def fake_gemini(**kwargs):
        return GeminiStructuredInsight(
            key_points=["資料重點已整理。"],
            conflicts=[],
            missing_data=[],
            coverage_notes=["coverage ok"],
        ), "completed"

    async def fake_claude(**kwargs):
        return ClaudeFinalReview(
            status="Strong",
            confidence="High",
            conclusion="資料面呈現偏正向，但仍需追蹤風險。",
            supporting_evidence=["資料重點已整理。"],
            key_risks=[],
            conflicting_signals=[],
            data_limitations=[],
            manual_review_required=[],
        ), "completed"

    monkeypatch.setattr(
        "backend.app.services.multi_agent_analysis.build_finmind_evidence",
        fake_evidence,
    )
    monkeypatch.setattr(
        "backend.app.services.multi_agent_analysis.run_gemini_structurer",
        fake_gemini,
    )
    monkeypatch.setattr(
        "backend.app.services.multi_agent_analysis.run_claude_finalizer",
        fake_claude,
    )

    response = await run_multi_agent_analysis("2330", question="整理重點")

    assert [stage.status for stage in response.analysis.agents] == [
        "completed",
        "completed",
        "completed",
    ]
    assert response.analysis.claude_final.confidence == "High"


def test_tw_agent_analysis_endpoint_uses_fixed_schema(monkeypatch):
    from backend.app.main import app

    async def fake_evidence(symbol: str):
        return _sample_packs(), ["valuation_missing"], False

    monkeypatch.setattr(
        "backend.app.services.multi_agent_analysis.build_finmind_evidence",
        fake_evidence,
    )
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    client = TestClient(app)
    resp = client.get("/tw/agent-analysis", params={"symbol": "2330"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "2330"
    assert body["analysis"]["pipeline_version"] == "finmind-gemini-claude-v1"
    assert body["analysis"]["agents"][0]["name"] == "FinMind Agent"
    assert body["analysis"]["gemini_structured"]["key_points"]
    assert "claude_final" in body["analysis"]
    text = str(body)
    for forbidden in ("買進", "賣出", "持有", "目標價"):
        assert forbidden not in text
