from __future__ import annotations

from backend.app.services.strategy.canslim.features import CanslimFeatures
from backend.app.services.strategy.canslim.params import load_params
from backend.app.services.strategy.canslim.pillar_screening import screen_S


def _f(**ov) -> CanslimFeatures:
    data = {
        "symbol": "2330", "as_of_date": "2026-01-02",
        "avg_turnover_20": 50_000_000, "up_down_volume_ratio_10": 1.5,
    }
    data.update(ov)
    return CanslimFeatures(**data)


def _p():
    return load_params()


def test_pass_needs_up_volume_and_not_contracting():
    v = screen_S(_f(volume_ratio_recent_vs_prior_20=1.4), {}, _p())
    assert v.status == "Pass"


def test_up_but_volume_contracting_is_weak():
    # up/down ratio passes but recent volume <= prior (上漲量縮) -> Weak, not Pass.
    v = screen_S(_f(volume_ratio_recent_vs_prior_20=0.7), {}, _p())
    assert v.status == "Weak"
    assert "上漲量縮" in v.reason or "contracting" in v.reason.lower()


def test_missing_expansion_data_falls_back_to_up_down_ratio_pass():
    # No volume_ratio_recent_vs_prior_20 -> not penalised, still Pass (backward compat).
    v = screen_S(_f(), {}, _p())
    assert v.status == "Pass"


def test_overheated_spike_near_high_is_capped_to_weak():
    # latest volume 5x the 20d avg while within 3% of the 52w high -> blow-off guard.
    v = screen_S(_f(avg_volume_20=1_000_000, latest_volume=5_000_000,
                    pct_from_52w_high=-0.01, volume_ratio_recent_vs_prior_20=1.5), {}, _p())
    assert v.status == "Weak"
    assert "overheated" in v.reason.lower()


def test_high_volume_not_extended_is_not_overheated():
    # Same spike but far from the high -> not a blow-off; normal Pass path.
    v = screen_S(_f(avg_volume_20=1_000_000, latest_volume=5_000_000,
                    pct_from_52w_high=-0.30, volume_ratio_recent_vs_prior_20=1.5), {}, _p())
    assert v.status == "Pass"


def test_below_liquidity_floor_is_fail():
    v = screen_S(_f(avg_turnover_20=1_000_000), {}, _p())
    assert v.status == "Fail"
