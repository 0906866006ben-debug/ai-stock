"""O'Neil D: cross-sectional float-size percentile overlay on the S pillar."""
from __future__ import annotations

from backend.app.services.strategy.canslim.features import CanslimFeatures
from backend.app.services.strategy.canslim.params import load_params
from backend.app.services.strategy.canslim.pillar_screening import screen_S


def _f(shares=None, **ov) -> CanslimFeatures:
    data = {
        "symbol": "2330", "as_of_date": "2026-01-02",
        "avg_turnover_20": 50_000_000, "up_down_volume_ratio_10": 1.5,
        "volume_ratio_recent_vs_prior_20": 1.4,  # base -> Pass
    }
    if shares is not None:
        data["shares_outstanding"] = shares
    data.update(ov)
    return CanslimFeatures(**data)


def _p():
    return load_params()


# universe of float sizes; 2330 placed at different ranks per test
def _universe(target_shares):
    base = {f"S{i}": float(i) for i in range(1, 11)}  # 1..10
    base["2330"] = float(target_shares)
    return base


def test_no_universe_is_noop_pass():
    assert screen_S(_f(shares=5.0), {}, _p(), universe_shares=None).status == "Pass"


def test_no_shares_is_noop_pass():
    assert screen_S(_f(shares=None), {}, _p(), universe_shares=_universe(5)).status == "Pass"


def test_small_float_adds_bonus_driver_keeps_pass():
    # 2330 smallest float in the universe -> bottom percentile -> bonus driver.
    v = screen_S(_f(shares=0.5), {}, _p(), universe_shares=_universe(0.5))
    assert v.status == "Pass"
    assert any("small-float" in d for d in v.drivers)


def test_mega_float_caps_pass_to_weak():
    # 2330 the largest float (top percentile) -> bloated supply -> Pass capped to Weak.
    v = screen_S(_f(shares=1000.0), {}, _p(), universe_shares=_universe(1000.0))
    assert v.status == "Weak"
    assert any("float" in w.lower() for w in v.data_warnings)


def test_mega_float_does_not_upgrade_a_fail():
    # Below liquidity floor -> Fail; mega float must not change a non-Pass verdict.
    v = screen_S(_f(shares=1000.0, avg_turnover_20=1_000_000), {}, _p(), universe_shares=_universe(1000.0))
    assert v.status == "Fail"
