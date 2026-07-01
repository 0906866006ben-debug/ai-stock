"""Phase 0 unit tests for the value-quant factor layer (value_factors.py).

Covers: Magic Formula EY/ROC hand-calc correctness, the Piotroski 9-point trigger, Shareholder
Yield logic (dividend + buyback + debt reduction, dilution flag), PIT boundary (a future-filed
quarter is invisible via the store gate), and missing-data -> None (never fabricated).
"""
from __future__ import annotations

import json

import pandas as pd
import pytest

from backend.app.services.strategy.canslim.params import load_params
from backend.app.services.strategy.value.value_factors import (
    magic_formula,
    piotroski_fscore,
    shareholder_yield,
)

PARAMS = load_params()


# ── fixture builders ──────────────────────────────────────────────────────────
def _raw(items: dict) -> str:
    """A FinMind-shaped raw_json string: [{"type": key, "value": v}, ...]."""
    return json.dumps([{"type": k, "value": v} for k, v in items.items()])


def _income_df(rows: list[tuple[str, dict]]) -> pd.DataFrame:
    """rows = [(period_end, {line_item: value})]."""
    return pd.DataFrame(
        [{"period_end": pe, "raw_json": _raw(items)} for pe, items in rows]
    )


def _bs_df(rows: list[tuple[str, dict]]) -> pd.DataFrame:
    return pd.DataFrame(
        [{"period_end": pe, "raw_json": _raw(items)} for pe, items in rows]
    )


def _cash_flow_df(rows: list[tuple[str, float]]) -> pd.DataFrame:
    return pd.DataFrame([{"period_end": pe, "cfo": cfo} for pe, cfo in rows])


def _per_df(yields: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"dividend_yield": yields})


# ── Magic Formula ──────────────────────────────────────────────────────────────
def test_magic_formula_ey_roc_hand_calc():
    """EBIT=100, EV=mc+long_debt-cash, ROC=EBIT/(PP&E + (CA-Cash-LTI))."""
    inc = _income_df([
        ("2023-03-31", {"OperatingIncome": 25}),
        ("2023-06-30", {"OperatingIncome": 25}),
        ("2023-09-30", {"OperatingIncome": 25}),
        ("2023-12-31", {"OperatingIncome": 25}),
    ])
    bs = _bs_df([
        ("2023-12-31", {
            "CashAndCashEquivalents": 200,
            "LongtermBorrowings": 300,
            "PropertyPlantAndEquipment": 500,
            "CurrentAssets": 400,
        }),
    ])
    out = magic_formula(financials=inc, balance_sheet=bs, market_cap=1000, params=PARAMS)

    assert out["ebit"] == pytest.approx(100.0)
    # EV = 1000 + 300 - 200 = 1100
    assert out["ev"] == pytest.approx(1100.0)
    # EY = 100 / 1100
    assert out["ey"] == pytest.approx(100.0 / 1100.0)
    # NWC = 400 - 200 - 0(LTI absent) = 200 ; capital = 500 + 200 = 700 ; ROC = 100/700
    assert out["roc"] == pytest.approx(100.0 / 700.0)
    # LongtermInvestments genuinely absent in FinMind data -> recorded, not fabricated.
    assert "LongtermInvestments" in out["missing"]


def test_magic_formula_missing_returns_none():
    """No financials -> EBIT/EY None; no balance sheet -> ROC None. Nothing fabricated."""
    out = magic_formula(financials=None, balance_sheet=None, market_cap=1000, params=PARAMS)
    assert out["ebit"] is None
    assert out["ey"] is None
    assert out["roc"] is None
    assert "ebit_ttm" in out["missing"]


def test_magic_formula_missing_market_cap():
    inc = _income_df([(f"2023-0{q}-30", {"OperatingIncome": 25}) for q in (3, 6, 9)]
                     + [("2023-12-31", {"OperatingIncome": 25})])
    bs = _bs_df([("2023-12-31", {"PropertyPlantAndEquipment": 500, "CurrentAssets": 400,
                                 "CashAndCashEquivalents": 200})])
    out = magic_formula(financials=inc, balance_sheet=bs, market_cap=None, params=PARAMS)
    assert out["ev"] is None
    assert out["ey"] is None          # EV unknown -> EY None
    assert out["roc"] is not None     # ROC does not need market cap
    assert "market_cap" in out["missing"]


# ── Piotroski F-Score ──────────────────────────────────────────────────────────
def _full_fscore_inputs():
    """Construct frames where all 9 Piotroski signals are TRUE."""
    # 8 income quarters: 2022 (4) weaker, 2023 (4) stronger -> ROA/GM/turnover all improve.
    inc_rows = []
    for pe in ("2022-03-31", "2022-06-30", "2022-09-30", "2022-12-31"):
        inc_rows.append((pe, {"Revenue": 100, "GrossProfit": 30, "OperatingIncome": 20,
                              "IncomeAfterTaxes": 15}))
    for pe in ("2023-03-31", "2023-06-30", "2023-09-30", "2023-12-31"):
        inc_rows.append((pe, {"Revenue": 120, "GrossProfit": 42, "OperatingIncome": 28,
                              "IncomeAfterTaxes": 20}))
    inc = _income_df(inc_rows)

    # Balance sheet: 5 periods. idx0=latest(2023-12-31), idx1=2023-09-30 used by F-Score.
    bs_rows = [
        ("2022-12-31", {"TotalLiabilitiesEquity": 1000, "CurrentAssets": 400, "CurrentLiabilities": 200,
                        "LongtermBorrowings": 200, "ShorttermBorrowings": 80, "CapitalStock": 330}),
        ("2023-03-31", {"TotalLiabilitiesEquity": 1000, "CurrentAssets": 410, "CurrentLiabilities": 205,
                        "LongtermBorrowings": 180, "ShorttermBorrowings": 70, "CapitalStock": 320}),
        ("2023-06-30", {"TotalLiabilitiesEquity": 1000, "CurrentAssets": 420, "CurrentLiabilities": 210,
                        "LongtermBorrowings": 170, "ShorttermBorrowings": 65, "CapitalStock": 310}),
        # idx1 (prev) -> current ratio 400/200=2.0, ltd 150, cap 300
        ("2023-09-30", {"TotalLiabilitiesEquity": 1000, "CurrentAssets": 400, "CurrentLiabilities": 200,
                        "LongtermBorrowings": 150, "ShorttermBorrowings": 55, "CapitalStock": 300}),
        # idx0 (latest) -> current ratio 500/200=2.5, ltd 100, cap 300
        ("2023-12-31", {"TotalLiabilitiesEquity": 1000, "CurrentAssets": 500, "CurrentLiabilities": 200,
                        "LongtermBorrowings": 100, "ShorttermBorrowings": 50, "CapitalStock": 300}),
    ]
    bs = _bs_df(bs_rows)
    # CFO for FY2023 > NI(=80) and > 0.
    cf = _cash_flow_df([("2023-12-31", 100.0)])
    return inc, bs, cf


def test_piotroski_full_nine_points():
    inc, bs, cf = _full_fscore_inputs()
    score = piotroski_fscore(financials=inc, balance_sheet=bs, cash_flow=cf, params=PARAMS)
    assert score == 9


def test_piotroski_without_cashflow_caps_below_nine():
    """No cash flow -> the 2 CFO signals can't fire -> at most 7."""
    inc, bs, _ = _full_fscore_inputs()
    score = piotroski_fscore(financials=inc, balance_sheet=bs, cash_flow=None, params=PARAMS)
    assert score is not None
    assert score <= 7
    assert score == 7   # all 7 non-cash signals true in this fixture


def test_piotroski_thin_history_returns_none():
    inc = _income_df([("2023-12-31", {"Revenue": 100, "IncomeAfterTaxes": 15})])
    bs = _bs_df([("2023-12-31", {"TotalLiabilitiesEquity": 1000})])
    score = piotroski_fscore(financials=inc, balance_sheet=bs, cash_flow=None, params=PARAMS)
    assert score is None


# ── Shareholder Yield ───────────────────────────────────────────────────────────
def test_shareholder_yield_components():
    _, bs, _ = _full_fscore_inputs()
    per = _per_df([2.5, 3.0])     # latest 3.0% -> 0.03
    out = shareholder_yield(balance_sheet=bs, per=per, market_cap=10000, params=PARAMS)

    assert out["div"] == pytest.approx(0.03)
    # CapitalStock: idx0=300, idx4=330 -> buyback (330-300)/330
    assert out["net_buyback"] == pytest.approx((330 - 300) / 330)
    assert out["diluted"] is False
    # debt: idx0 = 100+50 = 150 ; idx4 = 200+80 = 280 ; reduction/mc = (280-150)/10000
    assert out["net_debt_reduction"] == pytest.approx((280 - 150) / 10000)
    assert out["total"] == pytest.approx(0.03 + (30 / 330) + (130 / 10000))


def test_shareholder_yield_dilution_flagged_not_subtracted():
    """If CapitalStock GREW (share issuance), net_buyback is 0 and flagged, never negative."""
    bs = _bs_df([
        ("2022-12-31", {"CapitalStock": 300, "LongtermBorrowings": 100}),
        ("2023-03-31", {"CapitalStock": 320, "LongtermBorrowings": 100}),
        ("2023-06-30", {"CapitalStock": 340, "LongtermBorrowings": 100}),
        ("2023-09-30", {"CapitalStock": 360, "LongtermBorrowings": 100}),
        ("2023-12-31", {"CapitalStock": 400, "LongtermBorrowings": 100}),  # idx0=400 vs idx4=300
    ])
    per = _per_df([1.0])
    out = shareholder_yield(balance_sheet=bs, per=per, market_cap=10000, params=PARAMS)
    assert out["diluted"] is True
    assert out["net_buyback"] == 0.0        # issuance not subtracted
    assert out["net_buyback"] >= 0


def test_shareholder_yield_missing_dividend():
    _, bs, _ = _full_fscore_inputs()
    out = shareholder_yield(balance_sheet=bs, per=None, market_cap=10000, params=PARAMS)
    assert out["div"] is None
    assert "dividend_yield" in out["missing"]
    # total still computed from the available terms (buyback + debt reduction).
    assert out["total"] is not None


# ── PIT boundary (future filing invisible) ──────────────────────────────────────
def test_pit_boundary_future_filing_invisible(tmp_path):
    """A quarter FILED after as_of must not enter the factor via the store gate."""
    from backend.app.services.backtest.pit_fundamentals_store import PitFundamentalsStore

    store = PitFundamentalsStore(tmp_path / "pit.db")
    # Four real quarters filed on time (EBIT=100), plus a future quarter filed AFTER as_of.
    rows = [
        {"stock_id": "9999", "period_end": "2023-03-31", "filing_date": "2023-05-15",
         "raw_json": _raw({"OperatingIncome": 25})},
        {"stock_id": "9999", "period_end": "2023-06-30", "filing_date": "2023-08-14",
         "raw_json": _raw({"OperatingIncome": 25})},
        {"stock_id": "9999", "period_end": "2023-09-30", "filing_date": "2023-11-14",
         "raw_json": _raw({"OperatingIncome": 25})},
        {"stock_id": "9999", "period_end": "2023-12-31", "filing_date": "2024-03-31",
         "raw_json": _raw({"OperatingIncome": 25})},
        # Future quarter — filed 2024-05-15, must be invisible at as_of 2024-04-01.
        {"stock_id": "9999", "period_end": "2024-03-31", "filing_date": "2024-05-15",
         "raw_json": _raw({"OperatingIncome": 999})},
    ]
    store.upsert_financials(rows)
    bs_rows = [
        {"stock_id": "9999", "period_end": "2023-12-31", "filing_date": "2024-03-31",
         "raw_json": _raw({"PropertyPlantAndEquipment": 500, "CurrentAssets": 400,
                           "CashAndCashEquivalents": 200, "LongtermBorrowings": 300})},
    ]
    store.upsert_balance_sheet(bs_rows)

    as_of = "2024-04-01"
    fin = store.get_financials_as_of("9999", as_of, limit=8)
    bs = store.get_balance_sheet_as_of("9999", as_of, limit=8)
    out = magic_formula(financials=fin, balance_sheet=bs, market_cap=1000, params=PARAMS)

    # TTM EBIT uses the 4 on-time quarters (4 x 25 = 100); the 999 future quarter is excluded.
    assert out["ebit"] == pytest.approx(100.0)
