"""Tests for the single-bucket (long + short-timing) daily opportunities endpoint.

The endpoint fans out to several async fetchers and one sync industry map; we
patch those seams so the test is deterministic and offline. Focus: (i) output
carries long + mid + short buckets (mid = CANSLIM 領導股快照, unvalidated 觀察名單),
(ii) financials are excluded, (iii) long grading thresholds, (iv) short signals
attach to long candidates, (v) no_data.
"""
from __future__ import annotations

import pytest

from backend.app.services import file_cache
from backend.app.services import tw_daily_opportunities as opp


def _quote(name: str, close: float = 50.0, turnover: float = 100_000_000, change: float = 1.0):
    return {"name": name, "close": close, "turnover": turnover, "change_pct": change}


# A cheap→expensive ladder of 8 non-financial commons + one financial (2882).
# 1101 is the cheapest non-financial; 2882 is cheaper still but must be excluded.
_VALUATION = {
    "1101": {"per": 8.0, "pbr": 0.8, "yield": 6.0},
    "1102": {"per": 10.0, "pbr": 1.0, "yield": 5.0},
    "1103": {"per": 12.0, "pbr": 1.3, "yield": 4.5},
    "1104": {"per": 14.0, "pbr": 1.6, "yield": 4.0},
    "1105": {"per": 16.0, "pbr": 1.9, "yield": 3.0},
    "1106": {"per": 18.0, "pbr": 2.2, "yield": 2.5},
    "1107": {"per": 20.0, "pbr": 2.6, "yield": 2.0},
    "1108": {"per": 22.0, "pbr": 3.0, "yield": 1.5},
    "2882": {"per": 5.0, "pbr": 0.5, "yield": 8.0},  # financial: cheapest, MUST be excluded
}
_INDUSTRY = {sid: {"i": "水泥工業", "n": f"測試{sid}"} for sid in _VALUATION}
_INDUSTRY["2882"] = {"i": "金融保險", "n": "國泰金"}  # exact FinMind label

# Revenue: 1101 strong growth (→S), 1102 mild (→A), 1107 non-positive (gate drops it).
_REVENUE = {
    "1101": {"yoy": 15.0, "yoy_streak": 4, "new_high": True, "month": "2026-05"},
    "1102": {"yoy": 5.0, "yoy_streak": 2, "new_high": False, "month": "2026-05"},
    "1103": {"yoy": 8.0, "yoy_streak": 1, "new_high": False, "month": "2026-05"},
    "1104": {"yoy": 3.0, "yoy_streak": 1, "new_high": False, "month": "2026-05"},
    "1105": {"yoy": 2.0, "yoy_streak": 1, "new_high": False, "month": "2026-05"},
    "1106": {"yoy": 1.0, "yoy_streak": 1, "new_high": False, "month": "2026-05"},
    "1107": {"yoy": -4.0, "yoy_streak": 0, "new_high": False, "month": "2026-05"},  # dropped
    "1108": {"yoy": 1.0, "yoy_streak": 1, "new_high": False, "month": "2026-05"},
    "2882": {"yoy": 20.0, "yoy_streak": 6, "new_high": True, "month": "2026-05"},
}


@pytest.fixture(autouse=True)
def _no_cache(monkeypatch):
    monkeypatch.setattr(file_cache, "load", lambda *a, **k: None)
    monkeypatch.setattr(file_cache, "save", lambda *a, **k: None)


def _patch_sources(monkeypatch, quotes=None):
    quotes = _VALUATION.keys() if quotes is None else quotes
    q = {sid: _quote(_INDUSTRY[sid]["n"]) for sid in quotes}

    async def fake_day_all(client):
        return q

    async def fake_bwibbu(client):
        return {sid: dict(_VALUATION[sid]) for sid in q}

    async def fake_t86(client, days=10):
        return {}

    async def fake_revenues(client, sids, token):
        return {sid: dict(_REVENUE[sid]) for sid in sids if sid in _REVENUE}

    monkeypatch.setattr(opp, "_twse_day_all", fake_day_all)
    monkeypatch.setattr(opp, "_twse_bwibbu", fake_bwibbu)
    monkeypatch.setattr(opp, "_t86_recent_days", fake_t86)
    monkeypatch.setattr(opp, "_fetch_revenues", fake_revenues)
    monkeypatch.setattr(opp, "_stock_info_map", lambda: _INDUSTRY)


async def test_buckets_are_long_mid_short(monkeypatch):
    """mid（CANSLIM 領導股）於 2026-07-04 以快照制重新加入——未達驗證門檻的觀察名單。"""
    _patch_sources(monkeypatch)
    res = await opp.get_daily_opportunities()
    assert res["status"] == "ok"
    assert set(res["buckets"].keys()) == {"long", "mid", "short"}
    for it in res["buckets"]["mid"]:
        assert it["grade"] in {"S", "A", "B"}
        assert "快照" in it["basis"]  # 每項標示快照日期（誠實資料契約）
    # 未達驗證門檻的標註必須存在於 notices
    assert any("未達驗證門檻" in n for n in res["notices"])


async def test_financials_excluded(monkeypatch):
    _patch_sources(monkeypatch)
    res = await opp.get_daily_opportunities()
    long_ids = {it["stock_id"] for it in res["buckets"]["long"]}
    # 2882 is the cheapest name of all; if the industry filter were broken it would
    # top the value ranking. Its absence proves financials are excluded.
    assert "2882" not in long_ids
    assert "1101" in long_ids


async def test_long_grade_thresholds(monkeypatch):
    _patch_sources(monkeypatch)
    res = await opp.get_daily_opportunities()
    by_id = {it["stock_id"]: it for it in res["buckets"]["long"]}
    # 1101: cheapest (top percentile >= 0.85) AND yoy 15 (>=10) -> S
    assert by_id["1101"]["grade"] == "S"
    # 1107 has yoy <= 0 -> dropped by the revenue-growth gate
    assert "1107" not in by_id
    # every surfaced long item has positive revenue yoy
    assert all(it["metrics"]["revenue_yoy"] > 0 for it in res["buckets"]["long"])


async def test_short_attaches_to_long(monkeypatch):
    _patch_sources(monkeypatch)
    monkeypatch.setattr(opp, "_in_announcement_window", lambda m: True)
    res = await opp.get_daily_opportunities()
    long_ids = {it["stock_id"] for it in res["buckets"]["long"]}
    for it in res["buckets"]["short"]:
        assert it["metrics"]["from_bucket"] == "long"
        assert it["stock_id"] in long_ids
    # 1101 has new_high revenue in the (patched-open) announcement window -> a short signal
    assert "1101" in {it["stock_id"] for it in res["buckets"]["short"]}


async def test_no_data_when_quotes_unavailable(monkeypatch):
    _patch_sources(monkeypatch, quotes=[])

    async def empty_day_all(client):
        return {}

    monkeypatch.setattr(opp, "_twse_day_all", empty_day_all)
    res = await opp.get_daily_opportunities()
    assert res["status"] == "no_data"
