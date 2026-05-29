from datetime import datetime

import pytest

from backend.app.services.backtest.v2.walk_forward import make_walk_forward_splits, paired_windows


def _dt(value: str):
    return datetime.strptime(value, "%Y-%m-%d").date()


def test_5_windows_no_overlap():
    splits = make_walk_forward_splits("2022-01-01", "2022-12-31", n_windows=5)
    for previous, current in zip(splits, splits[1:]):
        assert _dt(previous.end_date) < _dt(current.start_date)


def test_train_ratio_respected():
    splits = make_walk_forward_splits("2022-01-01", "2022-04-10", n_windows=1, train_ratio=0.8)
    train, test = paired_windows(splits)[0]
    train_days = (_dt(train.end_date) - _dt(train.start_date)).days + 1
    test_days = (_dt(test.end_date) - _dt(test.start_date)).days + 1
    assert train_days == 80
    assert test_days == 20


def test_chronological_order_preserved():
    splits = make_walk_forward_splits("2023-01-01", "2023-03-31", n_windows=3)
    starts = [_dt(split.start_date) for split in splits]
    assert starts == sorted(starts)
    assert [split.name for split in splits] == [
        "win_0_train",
        "win_0_test",
        "win_1_train",
        "win_1_test",
        "win_2_train",
        "win_2_test",
    ]


def test_no_lookahead_in_test_window():
    for train, test in paired_windows(make_walk_forward_splits("2022-01-01", "2022-06-30", n_windows=3)):
        assert _dt(test.start_date) > _dt(train.end_date)


def test_single_window_equivalent_to_legacy_70_30():
    splits = make_walk_forward_splits("2022-01-01", "2022-04-10", n_windows=1, train_ratio=0.7)
    train, test = paired_windows(splits)[0]
    assert train.start_date == "2022-01-01"
    assert train.end_date == "2022-03-11"
    assert test.start_date == "2022-03-12"
    assert test.end_date == "2022-04-10"


def test_total_coverage_matches_input_range():
    splits = make_walk_forward_splits("2022-11-01", "2026-05-15", n_windows=5)
    assert splits[0].start_date == "2022-11-01"
    assert splits[-1].end_date == "2026-05-15"


def test_rejects_too_short_ranges():
    with pytest.raises(ValueError):
        make_walk_forward_splits("2022-01-01", "2022-01-04", n_windows=3)

