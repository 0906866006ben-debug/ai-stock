"""Walk-forward split generation for optimization v2."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional


@dataclass(frozen=True)
class Split:
    name: str
    start_date: str
    end_date: str
    is_test: bool
    window_index: int = 0


def make_walk_forward_splits(
    start: str,
    end: str,
    n_windows: int = 5,
    train_ratio: float = 0.8,
    step_size: Optional[int] = None,
) -> list[Split]:
    """Generate chronological train/test walk-forward splits.

    The default mode partitions the full date range into contiguous windows and
    splits each window into train/test segments. This keeps coverage complete
    and avoids accidental leakage between a window's train and test periods.
    """
    if n_windows < 1:
        raise ValueError("n_windows must be >= 1")
    if not 0 < train_ratio < 1:
        raise ValueError("train_ratio must be between 0 and 1")

    start_dt = _parse_date(start)
    end_dt = _parse_date(end)
    if end_dt < start_dt:
        raise ValueError("end must be on or after start")

    total_days = (end_dt - start_dt).days + 1
    if total_days < n_windows * 2:
        raise ValueError("date range is too short for train/test splits")

    if step_size is None:
        return _contiguous_windows(start_dt, total_days, n_windows, train_ratio)
    return _rolling_windows(start_dt, end_dt, n_windows, train_ratio, step_size)


def paired_windows(splits: list[Split]) -> list[tuple[Split, Split]]:
    """Return train/test pairs grouped by window index."""
    pairs: list[tuple[Split, Split]] = []
    for idx in sorted({split.window_index for split in splits}):
        window_splits = [split for split in splits if split.window_index == idx]
        trains = [split for split in window_splits if not split.is_test]
        tests = [split for split in window_splits if split.is_test]
        if len(trains) != 1 or len(tests) != 1:
            raise ValueError(f"window {idx} does not have exactly one train and one test split")
        pairs.append((trains[0], tests[0]))
    return pairs


def _contiguous_windows(start_dt: date, total_days: int, n_windows: int, train_ratio: float) -> list[Split]:
    base_len, remainder = divmod(total_days, n_windows)
    cursor = start_dt
    splits: list[Split] = []
    for idx in range(n_windows):
        window_len = base_len + (1 if idx < remainder else 0)
        splits.extend(_make_window(cursor, window_len, idx, train_ratio))
        cursor = cursor + timedelta(days=window_len)
    return splits


def _rolling_windows(
    start_dt: date,
    end_dt: date,
    n_windows: int,
    train_ratio: float,
    step_size: int,
) -> list[Split]:
    if step_size < 1:
        raise ValueError("step_size must be >= 1")
    total_days = (end_dt - start_dt).days + 1
    window_len = total_days - step_size * (n_windows - 1)
    if window_len < 2:
        raise ValueError("step_size leaves windows too short")

    splits: list[Split] = []
    for idx in range(n_windows):
        window_start = start_dt + timedelta(days=idx * step_size)
        actual_len = min(window_len, (end_dt - window_start).days + 1)
        splits.extend(_make_window(window_start, actual_len, idx, train_ratio))
    return splits


def _make_window(window_start: date, window_len: int, idx: int, train_ratio: float) -> list[Split]:
    train_len = max(1, int(window_len * train_ratio))
    if train_len >= window_len:
        train_len = window_len - 1
    test_len = window_len - train_len
    train_start = window_start
    train_end = train_start + timedelta(days=train_len - 1)
    test_start = train_end + timedelta(days=1)
    test_end = test_start + timedelta(days=test_len - 1)
    return [
        Split(
            name=f"win_{idx}_train",
            start_date=_format_date(train_start),
            end_date=_format_date(train_end),
            is_test=False,
            window_index=idx,
        ),
        Split(
            name=f"win_{idx}_test",
            start_date=_format_date(test_start),
            end_date=_format_date(test_end),
            is_test=True,
            window_index=idx,
        ),
    ]


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _format_date(value: date) -> str:
    return value.strftime("%Y-%m-%d")

