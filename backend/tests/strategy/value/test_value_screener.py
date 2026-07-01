"""Unit tests for the 優質長期持有 three-face screener (value_screener.py).

Covers each face's scoring + missing-data behavior, the composite renormalization
and grade bands, confidence haircuts, the no-fabrication end-to-end path over a
synthetic store + an empty PIT store, and the verb-free output contract.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from backend.app.services.backtest.historical_data_store import HistoricalDataStore
from backend.app.services.strategy.canslim.params import load_params
from backend.app.services.strategy.value import value_screener as vs

PARAMS = load_params()


def _bars(n=260, rising=True) -> pd.DataFrame:
    closes = [100.0 + i for i in range(n)] if rising else [400.0 - i for i in range(n)]
    return pd.DataFrame({"date": [f"d{i}" for i in range(n)], "close": closes})


def _fund(score=80.0, fscore=9, missing_inputs=(), flags=()):
    return {
        "score": score, "fscore": fscore, "ey": 0.12, "roc": 0.25, "sy_total": 0.06,
        "diluted": False, "missing_inputs": list(missing_inputs), "flags": list(flags),
    }


# ── 技術面 ────────────────────────────────────────────────────────────────────
def test_technical_face_uptrend_scores_high():
    out = vs.technical_face(_bars(rising=True), PARAMS)
    assert out["above_long_ma"] is True
    assert out["pct_from_52w_high"] == 0.0       # last close is the window high
    assert out["score"] == 100.0
    assert out["flags"] == []


def test_technical_face_downtrend_scores_low():
    out = vs.technical_face(_bars(rising=False), PARAMS)
    assert out["above_long_ma"] is False
    # 400 -> 141: ~ -65% from high, beyond the deep band -> zero proximity credit
    assert out["score"] == 0.0


def test_technical_face_thin_history_is_none():
    out = vs.technical_face(_bars(n=100), PARAMS)
    assert out["score"] is None
    assert "ohlcv_history_thin" in out["flags"]


# ── 籌碼面 ────────────────────────────────────────────────────────────────────
def test_chips_face_persistent_buying_scores_full():
    inst = pd.DataFrame({"foreign_net": [1000.0] * 60, "trust_net": [500.0] * 60})
    out = vs.chips_face(inst, PARAMS)
    assert out["score"] == 100.0
    assert out["inst_persistence"] == 1.0
    assert out["inst_cumulative_net"] > 0


def test_chips_face_empty_is_missing():
    out = vs.chips_face(pd.DataFrame(), PARAMS)
    assert out["score"] is None
    assert "institutional_missing" in out["flags"]


def test_chips_face_thin_history_is_none():
    inst = pd.DataFrame({"foreign_net": [1000.0] * 5, "trust_net": [0.0] * 5})
    out = vs.chips_face(inst, PARAMS)
    assert out["score"] is None
    assert "institutional_history_thin" in out["flags"]


def test_chips_face_persistent_selling_scores_zero():
    inst = pd.DataFrame({"foreign_net": [-1000.0] * 60, "trust_net": [-500.0] * 60})
    out = vs.chips_face(inst, PARAMS)
    assert out["score"] == 0.0


# ── composite + grade ─────────────────────────────────────────────────────────
def test_composite_core_grade_needs_high_total_and_fscore():
    comp = vs.composite_grade(
        _fund(score=90.0, fscore=9),
        {"score": 80.0, "inst_persistence": 0.9, "inst_cumulative_net": 1.0, "flags": []},
        {"score": 80.0, "above_long_ma": True, "pct_from_52w_high": -0.02, "flags": []},
        PARAMS,
    )
    assert comp["total_score"] == 85.0   # 0.5*90 + 0.25*80 + 0.25*80
    assert comp["screening_grade"] == vs.GRADE_CORE
    assert comp["confidence_score"] == 100


def test_composite_high_total_low_fscore_stays_watch():
    comp = vs.composite_grade(
        _fund(score=90.0, fscore=5),     # quality band not met -> never 核心觀察
        {"score": 80.0, "flags": []},
        {"score": 80.0, "flags": []},
        PARAMS,
    )
    assert comp["total_score"] == 85.0
    assert comp["screening_grade"] == vs.GRADE_WATCH


def test_composite_renormalizes_over_missing_face():
    comp = vs.composite_grade(
        _fund(score=80.0, fscore=8),
        {"score": None, "flags": ["institutional_missing"]},
        {"score": 60.0, "flags": []},
        PARAMS,
    )
    # (0.5*80 + 0.25*60) / 0.75 = 73.3; missing chips face lowers confidence
    assert comp["total_score"] == 73.3
    assert comp["screening_grade"] == vs.GRADE_WATCH
    assert "chips_face_missing" in comp["data_quality_flags"]
    assert comp["confidence_score"] == 80


def test_composite_below_watch_floor():
    comp = vs.composite_grade(
        _fund(score=30.0, fscore=3),
        {"score": 20.0, "flags": []},
        {"score": 20.0, "flags": []},
        PARAMS,
    )
    assert comp["screening_grade"] == vs.GRADE_BELOW


def test_composite_no_fundamentals_is_ungradable():
    comp = vs.composite_grade(
        {"score": None, "fscore": None, "ey": None, "roc": None, "sy_total": None,
         "diluted": False, "missing_inputs": [], "flags": ["fundamentals_unavailable"]},
        {"score": 90.0, "flags": []},
        {"score": 90.0, "flags": []},
        PARAMS,
    )
    assert comp["total_score"] is None
    assert comp["screening_grade"] == vs.GRADE_NO_DATA
    assert comp["confidence_score"] < 100


# ── end-to-end: empty PIT store never fabricates ─────────────────────────────
class _EmptyPit:
    def get_financials_as_of(self, *a, **k):
        return pd.DataFrame()

    get_balance_sheet_as_of = get_financials_as_of
    get_cash_flow_as_of = get_financials_as_of
    get_per_as_of = get_financials_as_of
    get_institutional_as_of = get_financials_as_of


def test_screen_symbol_value_empty_pit_is_no_data(tmp_path: Path):
    store = HistoricalDataStore(tmp_path / "ohlcv.db")
    start = pd.Timestamp("2020-01-01")
    store.upsert_rows([
        {"stock_id": "AAA", "date": (start + pd.Timedelta(days=i)).strftime("%Y-%m-%d"),
         "open": 100.0 + i, "high": 100.0 + i, "low": 100.0 + i, "close": 100.0 + i,
         "volume": 1_000_000, "turnover": (100.0 + i) * 1_000_000}
        for i in range(300)
    ])
    as_of = (start + pd.Timedelta(days=299)).strftime("%Y-%m-%d")

    row = vs.screen_symbol_value(store, _EmptyPit(), PARAMS, "AAA", as_of)
    assert row["screening_grade"] == vs.GRADE_NO_DATA
    assert row["total_score"] is None
    assert row["fundamental_score"] is None
    assert row["chips_score"] is None
    assert row["technical_score"] is not None       # 300 bars of OHLCV exist
    assert row["market_cap"] is None                # no balance sheet -> no shares
    assert "institutional_missing" in row["data_quality_flags"]
    assert row["confidence_score"] < 100


# ── output contract: verb-free, grades from the fixed set ─────────────────────
def test_grades_and_flags_are_verb_free():
    forbidden = ("買", "賣", "持有", "進場", "出場", "停損", "停利", "目標價")
    for text in (*vs.GRADES, vs.DISCLAIMER):
        for verb in forbidden:
            assert verb not in text, f"{verb!r} found in {text!r}"
    assert set(vs.GRADES) == {"核心觀察", "觀察", "未達標準", "資料不足"}
