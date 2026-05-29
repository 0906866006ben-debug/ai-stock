"""Whole-market ranking: rows produced, sorted by overall_score, columns present."""
from __future__ import annotations

import pandas as pd

from backend.app.models.screener_schemas import CanslimFactorScore, CanslimFullResult, ScreeningResult
from backend.app.services.strategy.canslim import canslim_ranking as cr
from backend.app.services.strategy.canslim.canslim_ranking import RANK_COLUMNS, rank_universe
from backend.app.services.strategy.canslim.params import load_params


def _full(stock_id, score, grade):
    sr = ScreeningResult(
        stock_id=stock_id, as_of_date="2025-06-30", candidate_grade=grade, canslim_match="x",
        pillars={p: "Pass" for p in "CANSLIM"}, market_regime="risk_on",
        interpretation="x", action_type="Watchlist Candidate", structure_status="intact",
    )
    factors = [CanslimFactorScore(factor=f, status="Pass", score=score) for f in ("C", "A", "N", "S", "L", "I", "M")]
    return ScreeningResultPair(sr, CanslimFullResult(
        stock_id=stock_id, as_of_date="2025-06-30", overall_score=score, grade=grade,
        pass_status="WATCHLIST", confidence="MEDIUM", risk_level="MEDIUM",
        per_factor_scores=factors, data_quality="HIGH", screening_result=sr,
    ))


class ScreeningResultPair:
    def __init__(self, sr, full): self.sr = sr; self.full = full


def test_rank_universe_sorts_and_has_columns(monkeypatch):
    # Three fake symbols with different scores -> ranked desc, all columns present.
    scores = {"AAA": (60, "B"), "BBB": (85, "A"), "CCC": (40, "C")}
    pairs = {k: _full(k, v[0], v[1]) for k, v in scores.items()}

    monkeypatch.setattr(cr, "get_universe_as_of", lambda *a, **k: ["AAA", "BBB", "CCC"])
    monkeypatch.setattr(cr, "_market_features_for_entry", lambda *a, **k: None)
    monkeypatch.setattr(cr, "_universe_returns_as_of", lambda *a, **k: {})
    monkeypatch.setattr(cr, "universe_shares_as_of", lambda *a, **k: {})
    monkeypatch.setattr(cr, "build_pit_inputs", lambda *a, **k: ({}, {}, None))
    monkeypatch.setattr(cr, "build_screening_result", lambda symbol, *a, **k: pairs[symbol].sr)
    monkeypatch.setattr(cr, "build_full_result", lambda r, params=None: pairs[r.stock_id].full)

    df = rank_universe("2025-06-30", object(), object(), candidate_symbols=["AAA", "BBB", "CCC"], params=load_params())
    assert list(df.columns) == RANK_COLUMNS
    assert df["stock_id"].tolist() == ["BBB", "AAA", "CCC"]   # 85 > 60 > 40
    assert df["rank"].tolist() == [1, 2, 3]
    assert df.iloc[0]["grade"] == "A" and df.iloc[0]["C_score"] == 85


def test_empty_universe_returns_empty_columns(monkeypatch):
    monkeypatch.setattr(cr, "get_universe_as_of", lambda *a, **k: [])
    df = rank_universe("2025-06-30", object(), object(), candidate_symbols=[], params=load_params())
    assert df.empty and list(df.columns) == RANK_COLUMNS


def test_symbol_error_is_skipped(monkeypatch):
    pair = _full("OK", 70, "B")
    monkeypatch.setattr(cr, "get_universe_as_of", lambda *a, **k: ["OK", "BAD"])
    monkeypatch.setattr(cr, "_market_features_for_entry", lambda *a, **k: None)
    monkeypatch.setattr(cr, "_universe_returns_as_of", lambda *a, **k: {})
    monkeypatch.setattr(cr, "universe_shares_as_of", lambda *a, **k: {})
    monkeypatch.setattr(cr, "build_pit_inputs", lambda *a, **k: ({}, {}, None))

    def screen(symbol, *a, **k):
        if symbol == "BAD":
            raise ValueError("boom")
        return pair.sr
    monkeypatch.setattr(cr, "build_screening_result", screen)
    monkeypatch.setattr(cr, "build_full_result", lambda r, params=None: pair.full)

    df = rank_universe("2025-06-30", object(), object(), candidate_symbols=["OK", "BAD"], params=load_params())
    assert df["stock_id"].tolist() == ["OK"]  # BAD skipped, no crash
