from backend.app.services.strategy.canslim.aggregator import AggregateResult, _achievable_signal_max, aggregate
from backend.app.services.strategy.canslim.base_detector import BasePattern
from backend.app.services.strategy.canslim.params import load_params
from backend.app.services.strategy.canslim.types import RuleResult


def _base(score: int = 0, pattern_type: str = "none") -> BasePattern:
    return BasePattern(pattern_type=pattern_type, quality_score=score)


def test_signal_pillar_caps_are_enforced():
    params = load_params()
    caps = params["scoring"]["signal"]["pillar_caps"]
    result = aggregate(
        [
            RuleResult("G-1", True, signal_delta=999),
            RuleResult("T-1", True, signal_delta=999),
            RuleResult("T-2", True, signal_delta=999),
            RuleResult("SD-2", True, signal_delta=999),
            RuleResult("I-1", True, signal_delta=999),
        ],
        _base(),
        "swing_term",
        params,
    )

    assert result.pillar_breakdown["growth_quality"] == caps["growth_quality"]
    assert result.pillar_breakdown["technical_leadership"] == caps["technical_leadership"]
    assert result.pillar_breakdown["breakout_catalyst"] == caps["breakout_catalyst"]
    assert result.pillar_breakdown["supply_demand"] == caps["supply_demand"]
    assert result.pillar_breakdown["institutional"] == caps["institutional"]
    assert result.signal_raw == params["scoring"]["signal"]["range_max"]
    assert result.signal_achievable_max == _achievable_signal_max("swing_term", params)
    assert result.signal_score == params["scoring"]["signal"]["range_max"]


def test_hard_block_reports_block_but_keeps_scores_independent():
    params = load_params()
    result = aggregate(
        [
            RuleResult("G-2", True, signal_delta=20, confidence_delta=15),
            RuleResult("R-6", True, hard_block=True),
        ],
        _base(),
        "long_term",
        params,
    )

    assert result.hard_blocked is True
    assert result.blocking_rule_ids == ["R-6"]
    assert result.signal_score > 0
    assert result.grade != "C" or result.signal_score >= params["scoring"]["grades"]["C_signal_min"]
    assert "R-6" in result.triggered_rule_ids


def test_confidence_clamps_and_low_confidence_flag():
    params = load_params()
    high = aggregate([RuleResult("G-1", True, confidence_delta=999)], _base(), "swing_term", params)
    low = aggregate(
        [RuleResult("G-1", False, confidence_delta=-999), RuleResult("R-4", True, hard_block=True)],
        _base(),
        "swing_term",
        params,
    )

    assert high.confidence_score == params["scoring"]["confidence"]["range_max"]
    assert high.low_confidence is False
    assert low.confidence_score == params["scoring"]["confidence"]["range_min"]
    assert low.low_confidence is True


def test_grade_bands_follow_yaml_thresholds():
    params = load_params()
    grades = params["scoring"]["grades"]

    s = aggregate(
        [
            RuleResult("G-1", True, signal_delta=30),
            RuleResult("T-1", True, signal_delta=25),
            RuleResult("T-2", True, signal_delta=20),
        ],
        _base(),
        "swing_term",
        params,
    )
    a = aggregate(
        [RuleResult("G-1", True, signal_delta=30), RuleResult("T-1", True, signal_delta=25)],
        _base(),
        "swing_term",
        params,
    )
    b = aggregate(
        [RuleResult("G-1", True, signal_delta=30), RuleResult("SD-2", True, signal_delta=5)],
        _base(),
        "swing_term",
        params,
    )
    c = aggregate([], _base(), "swing_term", params)

    assert s.signal_score == grades["S_signal_min"]
    assert s.grade == "S"
    assert a.signal_score == grades["A_signal_min"]
    assert a.grade == "A"
    assert b.signal_score == grades["B_signal_min"]
    assert b.grade == "B"
    assert c.grade == "C"
    assert c.signal_score == grades["C_signal_min"]


def test_partial_match_still_surfaces_as_graded_result():
    params = load_params()
    result = aggregate(
        [
            RuleResult("G-4", True, signal_delta=10),
            RuleResult("T-1", True, signal_delta=15),
            RuleResult("I-2", False),
        ],
        _base(),
        "swing_term",
        params,
    )

    assert isinstance(result, AggregateResult)
    assert result.hard_blocked is False
    assert result.signal_score > 0
    assert result.grade in {"B", "C"}
    assert result.triggered_rule_ids == ["G-4", "T-1"]


def test_base_pattern_quality_contributes_to_breakout_pillar():
    params = load_params()
    cap = params["scoring"]["signal"]["pillar_caps"]["breakout_catalyst"]
    result = aggregate([], _base(score=50, pattern_type="cup_and_handle"), "swing_term", params)

    assert result.pillar_breakdown["breakout_catalyst"] == round(0.5 * cap)
    assert result.signal_raw == result.pillar_breakdown["breakout_catalyst"]
    assert result.signal_score == round(result.signal_raw / result.signal_achievable_max * 100)


def test_data_warnings_are_preserved_from_rules_and_base():
    params = load_params()
    result = aggregate(
        [RuleResult("R-4", False, data_warning="event calendar unknown")],
        BasePattern(pattern_type="none", quality_score=0, data_warnings=["base weak"]),
        "short_term",
        params,
    )

    assert "event calendar unknown" in result.data_warnings
    assert "base weak" in result.data_warnings


def test_short_term_full_breakout_reaches_S():
    params = load_params()
    result = aggregate(
        [
            RuleResult("T-2", True, signal_delta=params["technical"]["rules"]["T-2"]["effects"]["signal_delta"]),
            RuleResult("T-4", True, signal_delta=params["technical"]["rules"]["T-4"]["effects"]["signal_delta"]),
            RuleResult("T-5", True, signal_delta=params["technical"]["rules"]["T-5"]["effects"]["signal_delta"]),
        ],
        _base(score=100, pattern_type="flat_base"),
        "short_term",
        params,
    )

    assert result.signal_achievable_max == _achievable_signal_max("short_term", params)
    assert result.signal_raw == result.signal_achievable_max
    assert result.signal_score == params["scoring"]["signal"]["range_max"]
    assert result.grade == "S"


def test_long_term_achievable_below_100():
    params = load_params()
    result = aggregate(
        [
            RuleResult("G-2", True, signal_delta=params["growth"]["rules"]["G-2"]["effects"]["signal_delta"]),
            RuleResult("T-3", True, signal_delta=params["technical"]["rules"]["T-3"]["effects"]["signal_delta"]),
        ],
        _base(score=50, pattern_type="cup_and_handle"),
        "long_term",
        params,
    )

    assert result.signal_achievable_max == _achievable_signal_max("long_term", params)
    assert result.signal_achievable_max < params["scoring"]["signal"]["range_max"]
    assert result.signal_raw < result.signal_achievable_max
    assert result.signal_score >= params["scoring"]["grades"]["A_signal_min"]
    assert result.grade == "A"


def test_swing_missing_fundamentals_normalizes_low():
    params = load_params()
    result = aggregate(
        [
            RuleResult("T-1", True, signal_delta=params["technical"]["rules"]["T-1"]["effects"]["signal_delta"]),
            RuleResult("G-1", False, confidence_delta=params["growth"]["rules"]["G-1"]["effects"]["missing_data_confidence_delta"]),
            RuleResult("G-2", False, confidence_delta=params["growth"]["rules"]["G-2"]["effects"]["missing_data_confidence_delta"]),
            RuleResult("I-1", False, confidence_delta=params["institutional"]["rules"]["I-1"]["effects"]["missing_data_confidence_delta"]),
        ],
        _base(),
        "swing_term",
        params,
    )

    assert result.signal_achievable_max == _achievable_signal_max("swing_term", params)
    assert result.signal_raw == params["technical"]["rules"]["T-1"]["effects"]["signal_delta"]
    assert result.signal_score < params["scoring"]["grades"]["B_signal_min"]
    assert result.grade == "C"
    assert result.low_confidence is True
