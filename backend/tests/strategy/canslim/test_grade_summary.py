from __future__ import annotations

import asyncio

from backend.app.services.strategy.canslim.grade_summary import (
    GradeSummary,
    build_deterministic_summary,
    summarize_grade,
    summarize_batch,
)
from backend.app.services.strategy.canslim.screening_language import (
    contains_forbidden_action_language,
)


def _card(**over):
    base = {
        "stock_id": "3481",
        "grade": "B",
        "signal": 52,
        "risk": 20,
        "confidence": 80,
        "pillars": {"C": "Fail", "A": "Fail", "N": "Pass", "S": "Weak",
                    "L": "Pass", "I": "Pass", "M": "Pass"},
        "invalidation": ["跌破20日均線:波段短期轉弱", "價漲量縮:量價背離"],
        "structure_status": "weakening",
        "durability_score": 52.0,
        "durability_components": {"op_margin_stability": 0.85, "roe_trend": 0.35,
                                  "earnings_purity": 0.7, "institutional_flow": 0.6},
    }
    base.update(over)
    return base


def test_deterministic_summary_has_three_sections():
    s = build_deterministic_summary(_card())
    assert isinstance(s, GradeSummary)
    assert s.source == "template"
    assert "B 級" in s.why_grade
    assert s.key_risks  # non-empty
    assert "耐久度" in s.durability_note


def test_summary_reports_earnings_cap():
    # C & A both Fail -> note that the grade is capped by weak earnings.
    s = build_deterministic_summary(_card())
    assert "獲利" in s.why_grade


def test_summary_lists_passing_pillars():
    s = build_deterministic_summary(_card())
    assert "法人支持" in s.why_grade or "領先強度" in s.why_grade


def test_durability_note_marks_strong_and_weak():
    s = build_deterministic_summary(_card())
    assert "營益率穩定" in s.durability_note   # strong (0.85)
    assert "52" in s.durability_note


def test_no_durability_data():
    s = build_deterministic_summary(_card(durability_score=None, durability_components={}))
    assert "不足" in s.durability_note


def test_summary_is_verb_free():
    s = build_deterministic_summary(_card())
    for text in (s.why_grade, s.key_risks, s.durability_note):
        assert not contains_forbidden_action_language(text)


def test_summarize_grade_falls_back_to_template_without_gemini(monkeypatch):
    # No GEMINI_API_KEY -> deterministic template.
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    s = asyncio.run(summarize_grade(_card()))
    assert s.source == "template"
    assert s.why_grade


def test_batch_keys_by_stock_id(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    cards = [_card(stock_id="3481"), _card(stock_id="2330", grade="C")]
    out = asyncio.run(summarize_batch(cards, concurrency=2))
    assert set(out.keys()) == {"3481", "2330"}
    assert all(isinstance(v, GradeSummary) for v in out.values())
