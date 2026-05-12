import pytest

from backend.app.services.yahoo_news import get_external_news


@pytest.mark.asyncio
async def test_external_news_mock_has_multiple_items_per_category(monkeypatch):
    monkeypatch.delenv("FINMIND_API_KEY", raising=False)

    data = await get_external_news()

    assert data["status"] == "mock"
    for category, items in data["categories"].items():
        assert len(items) >= 3, f"{category} should have at least 3 news items"
