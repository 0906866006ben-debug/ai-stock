from __future__ import annotations

from backend.app.services.strategy.canslim.features import CanslimFeatures
from backend.app.services.strategy.canslim.params import load_params
from backend.app.services.strategy.canslim.pillar_screening import screen_I


def _f(**ov) -> CanslimFeatures:
    data = {"symbol": "2330", "as_of_date": "2026-01-02", "avg_volume_20": 1000.0}
    data.update(ov)
    return CanslimFeatures(**data)


def _p():
    return load_params()


def test_both_positive_strong_accumulation_is_pass():
    # cumulative 500 vs 1000 avg vol = 0.5x >= 0.30 strength -> Pass.
    v = screen_I(_f(foreign_net_5=[100] * 5, trust_net_5=[100] * 5), {}, _p())
    assert v.status == "Pass"


def test_both_positive_light_accumulation_is_weak():
    # both net-positive every day but only 0.05x avg vol -> too light -> Weak.
    v = screen_I(_f(foreign_net_5=[10] * 5, trust_net_5=[10] * 5), {}, _p())
    assert v.status == "Weak"
    assert "light" in v.reason.lower()


def test_missing_avg_volume_falls_back_to_daycount_pass():
    v = screen_I(_f(avg_volume_20=None, foreign_net_5=[100] * 5, trust_net_5=[100] * 5), {}, _p())
    assert v.status == "Pass"


def test_both_net_negative_is_fail():
    v = screen_I(_f(foreign_net_5=[-10] * 5, trust_net_5=[-10] * 5), {}, _p())
    assert v.status == "Fail"


def test_foreign_strong_trust_zero_is_pass():
    # 投信=0 must not block a strong 外資 accumulation (the common TW case).
    v = screen_I(_f(foreign_net_5=[100] * 5, trust_net_5=[0] * 5), {}, _p())
    assert v.status == "Pass"


def test_one_group_distributing_is_weak():
    # foreign buying but trust net-selling -> a group is distributing -> Weak, not Pass.
    v = screen_I(_f(foreign_net_5=[100] * 5, trust_net_5=[-10] * 5), {}, _p())
    assert v.status == "Weak"
