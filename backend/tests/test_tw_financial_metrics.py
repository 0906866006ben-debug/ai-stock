from backend.app.services.tw_financial_metrics import format_metrics_for_narrative


def test_format_metrics_for_narrative_handles_none_values():
    narrative = format_metrics_for_narrative({
        "source": "test",
        "is_mock": False,
        "current_price": None,
        "market_cap": None,
        "pe_ratio": None,
        "pb_ratio": "bad",
        "revenue_yoy": 12.345,
    })

    assert "股價: TWD N/A" in narrative
    assert "市值: TWD N/A" in narrative
    assert "本益比 (Trailing P/E): N/Ax" in narrative
    assert "本淨比 (P/B): N/Ax" in narrative
    assert "營收YoY: 12.3%" in narrative
