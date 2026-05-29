import pandas as pd

from backend.app.services.strategy.canslim.base_detector import BasePattern, detect_base
from backend.app.services.strategy.canslim.params import load_params


def _bars(closes, volumes=None):
    volumes = volumes or [1000.0] * len(closes)
    rows = []
    for idx, (close, volume) in enumerate(zip(closes, volumes)):
        rows.append(
            {
                "date": f"2024-01-{idx + 1:02d}",
                "open": close,
                "high": close * 1.002,
                "low": close * 0.998,
                "close": close,
                "volume": volume,
            }
        )
    return pd.DataFrame(rows)


def _cup_closes(*, bottom=78.0, handle_low=97.0, breakout_close=103.0):
    return [
        96,
        98,
        100,
        99,
        98,
        96,
        94,
        92,
        90,
        87,
        84,
        81,
        bottom,
        80,
        82,
        84,
        86,
        88,
        90,
        92,
        94,
        96,
        97,
        98,
        99,
        100,
        101,
        100,
        99,
        handle_low,
        98,
        99,
        100,
        100,
        99,
        100,
        100,
        100,
        100,
        100,
        breakout_close,
    ]


def _cup_volumes(*, dry_handle=True, breakout=True):
    cup = [2000.0] * 27
    handle = [1200.0] * 13
    if not dry_handle:
        handle = [1900.0] * 13
    last = 1800.0 if breakout else 1300.0
    return [*cup, *handle, last]


def test_detects_clean_cup_and_handle_with_breakout():
    params = load_params()
    pattern = detect_base(_bars(_cup_closes(), _cup_volumes()), params)

    assert isinstance(pattern, BasePattern)
    assert pattern.pattern_type == "cup_and_handle"
    assert pattern.quality_score >= 90
    assert pattern.breakout_confirmed is True
    assert pattern.handle_in_upper_half is True
    assert pattern.pivot_price is not None


def test_cup_too_deep_is_not_cup_and_has_lower_score():
    params = load_params()
    pattern = detect_base(_bars(_cup_closes(bottom=55.0), _cup_volumes()), params)

    assert pattern.pattern_type != "cup_and_handle"
    assert pattern.quality_score < 90


def test_large_handle_pullback_keeps_partial_cup_score():
    params = load_params()
    pattern = detect_base(_bars(_cup_closes(handle_low=82.0), _cup_volumes()), params)

    assert pattern.pattern_type == "cup_and_handle"
    assert pattern.handle_pullback is not None
    assert pattern.handle_pullback > params["base_geometry"]["cup_and_handle"]["handle_pullback_max_upper"]
    assert 0 < pattern.quality_score < 90


def test_short_base_returns_none_without_blocking_semantics():
    params = load_params()
    pattern = detect_base(_bars([100, 99, 98, 99, 100]), params)

    assert pattern.pattern_type == "none"
    assert pattern.quality_score == 0
    assert "base_length_weeks" in pattern.missing_fields


def test_detects_clean_flat_base_fallback():
    params = load_params()
    closes = [100, 101, 100.5, 99.5, 100.2, 101.2, 100.8, 99.9, 100.1, 101.0] * 4
    pattern = detect_base(_bars(closes), params)

    assert pattern.pattern_type == "flat_base"
    assert pattern.quality_score >= 60
    assert pattern.pivot_price is not None


def test_no_breakout_volume_still_detects_pattern_with_partial_score():
    params = load_params()
    pattern = detect_base(_bars(_cup_closes(), _cup_volumes(breakout=False)), params)

    assert pattern.pattern_type == "cup_and_handle"
    assert pattern.breakout_confirmed is False
    assert 0 < pattern.quality_score < 100
