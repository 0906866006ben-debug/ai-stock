import pytest


_SAMPLE_CHART = [
    {"time": f"2025-01-{d:02d}", "open": 940.0, "high": 960.0,
     "low": 935.0, "close": float(940 + d), "volume": 1_000_000 + d * 1000}
    for d in range(1, 26)
]


@pytest.mark.asyncio
async def test_mock_returned_when_no_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from backend.app.services.tw_ai_analysis import get_tw_ai_analysis
    result, source = await get_tw_ai_analysis(
        symbol="2330", company_name="台積電", market_type="TWSE",
        current_price=965.0, price_change_percent=1.5,
        chart_data=_SAMPLE_CHART, news=[],
    )
    assert source == "mock"
    assert result["trend"] in ("看漲", "看跌", "中立")
    assert 0.0 <= result["confidence"] <= 1.0
    assert isinstance(result["risks"], list)
    assert isinstance(result["catalysts"], list)
    assert result["summary"]
    assert result["recommendation"]


def test_compute_indicators_ma5_ma20():
    from backend.app.services.tw_ai_analysis import _compute_indicators
    indicators = _compute_indicators(_SAMPLE_CHART)
    expected_ma5 = sum(r["close"] for r in _SAMPLE_CHART[-5:]) / 5
    assert abs(indicators["ma5"] - expected_ma5) < 0.01
    expected_ma20 = sum(r["close"] for r in _SAMPLE_CHART[-20:]) / 20
    assert abs(indicators["ma20"] - expected_ma20) < 0.01


def test_compute_indicators_price_changes():
    from backend.app.services.tw_ai_analysis import _compute_indicators
    indicators = _compute_indicators(_SAMPLE_CHART)
    closes = [r["close"] for r in _SAMPLE_CHART]
    expected_5d = (closes[-1] - closes[-6]) / closes[-6] * 100
    assert abs(indicators["price_5d_change"] - expected_5d) < 0.01


def test_build_prompt_no_news():
    from backend.app.services.tw_ai_analysis import _build_prompt
    prompt = _build_prompt(
        symbol="2330", company_name="台積電", market_type="TWSE",
        current_price=965.0, price_change_percent=1.5,
        chart_data=_SAMPLE_CHART, news=[],
    )
    assert "目前沒有可靠新聞資料" in prompt
    assert "台積電" in prompt
    assert "2330" in prompt


def test_build_prompt_with_news():
    from backend.app.services.tw_ai_analysis import _build_prompt
    news = [{"title": "台積電業績亮眼", "source": "經濟日報"}]
    prompt = _build_prompt(
        symbol="2330", company_name="台積電", market_type="TWSE",
        current_price=965.0, price_change_percent=1.5,
        chart_data=_SAMPLE_CHART, news=news,
    )
    assert "台積電業績亮眼" in prompt
