"""MED-1: month-revenue YoY must join prior year by (year, month), robustly."""
from __future__ import annotations

import pandas as pd

from backend.app.services.strategy.canslim.pit_inputs import _month_revenue_yoy


def test_yoy_joins_despite_day_of_month_drift():
    # Same month across years but different day-of-month — exact-string join would
    # have dropped these; (year, month) keying must still pair them.
    rev = pd.DataFrame({
        "date": ["2023-01-10", "2023-02-05", "2024-01-31", "2024-02-29"],
        "revenue": [100.0, 200.0, 150.0, 300.0],
    })
    out = _month_revenue_yoy(rev)
    # 2024-01 vs 2023-01: 150/100-1 = 0.5 ; 2024-02 vs 2023-02: 300/200-1 = 0.5
    assert out == [0.5, 0.5]


def test_leap_day_row_does_not_crash():
    rev = pd.DataFrame({"date": ["2020-02-29", "2021-02-28"], "revenue": [100.0, 120.0]})
    out = _month_revenue_yoy(rev)  # must not raise on Feb-29 arithmetic
    assert out == [0.2]


def test_no_prior_year_yields_empty():
    rev = pd.DataFrame({"date": ["2024-03-10", "2024-04-10"], "revenue": [100.0, 110.0]})
    assert _month_revenue_yoy(rev) == []


def test_zero_or_missing_prior_skipped():
    rev = pd.DataFrame({
        "date": ["2023-05-10", "2024-05-10"],
        "revenue": [0.0, 120.0],  # prior is 0 -> skip (no division)
    })
    assert _month_revenue_yoy(rev) == []
