import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch):
    from backend.app.main import app  # triggers load_dotenv first
    monkeypatch.delenv("FINMIND_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    return TestClient(app)


def test_analyze_tw_mock_response(client):
    resp = client.get("/analyze/tw", params={"symbol": "2330"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "2330"
    assert body["currency"] == "TWD"
    assert body["data_source"] == "mock"
    assert body["analysis_source"] == "mock"
    assert body["disclaimer"] == "本分析僅供參考，不構成投資建議。"
    assert body["trend"] in ("看漲", "看跌", "中立")
    assert isinstance(body["chart_data"], list)
    assert len(body["chart_data"]) > 0
    assert "time" in body["chart_data"][0]
    assert "open" in body["chart_data"][0]
    assert isinstance(body["recent_news"], list)
    assert "analyzed_at" in body


def test_analyze_tw_etf_symbol(client):
    resp = client.get("/analyze/tw", params={"symbol": "00878"})
    assert resp.status_code == 200
    assert resp.json()["symbol"] == "00878"


def test_analyze_tw_rejects_invalid_symbol(client):
    resp = client.get("/analyze/tw", params={"symbol": "AAPL"})
    assert resp.status_code == 422


def test_analyze_tw_rejects_short_symbol(client):
    resp = client.get("/analyze/tw", params={"symbol": "23"})
    assert resp.status_code == 422


def test_analyze_tw_rejects_seven_digit(client):
    resp = client.get("/analyze/tw", params={"symbol": "1234567"})
    assert resp.status_code == 422


def test_existing_us_route_unchanged(client):
    """The original /analyze endpoint must still respond (with mock data)."""
    resp = client.get("/analyze", params={"symbol": "AAPL"})
    assert resp.status_code == 200
    assert "symbol" in resp.json()


def test_tw_analysis_daily_cache_never_reuses_mock_market_data():
    from backend.app.main import _is_reusable_tw_analysis_cache

    assert _is_reusable_tw_analysis_cache(
        {"analysis_source": "ai", "data_source": "live"}
    )
    assert not _is_reusable_tw_analysis_cache(
        {"analysis_source": "ai", "data_source": "mock"}
    )
    assert not _is_reusable_tw_analysis_cache(
        {"analysis_source": "mock", "data_source": "live"}
    )
