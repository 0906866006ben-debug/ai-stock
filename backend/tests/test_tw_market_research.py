from __future__ import annotations

from backend.app.services.tw_market_research import _fetch_gemini_grounded_search


async def test_fetch_gemini_grounded_search_uses_installed_google_genai(monkeypatch):
    import google.genai as genai

    calls = []

    class FakeModels:
        def generate_content(self, **kwargs):
            calls.append(kwargs)

            class Response:
                text = "市場看漲，分析師維持 buy 評等。"

            return Response()

    class FakeClient:
        def __init__(self, *, api_key: str):
            self.api_key = api_key
            self.models = FakeModels()

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-test")
    monkeypatch.delenv("GEMINI_FALLBACK_MODELS", raising=False)
    monkeypatch.setattr(genai, "Client", FakeClient)

    result = await _fetch_gemini_grounded_search("2330", "台積電")

    assert result["narrative_source"] == "grounded"
    assert result["analyst_consensus"] == "看漲"
    assert calls[0]["model"] == "gemini-test"
    assert "2330 台積電" in calls[0]["contents"]
    assert calls[0]["config"].tools
