from __future__ import annotations

import json

import pandas as pd

from backend.app.services.strategy.canslim.durability import compute_durability
from backend.app.services.strategy.canslim.params import load_params

PARAMS = load_params()


def _fin(rows: list[dict]) -> pd.DataFrame:
    """rows: list of {period_end, **line_items}."""
    out = []
    for r in rows:
        pe = r.pop("period_end")
        out.append({"period_end": pe, "eps": r.get("EPS", 1.0),
                    "raw_json": json.dumps([{"type": k, "value": v} for k, v in r.items()])})
    return pd.DataFrame(out)


def _income(n: int, *, rev=100.0, opi=30.0, gp=55.0, ni=28.0) -> pd.DataFrame:
    base = pd.Timestamp("2019-03-31")
    rows = []
    for i in range(n):
        pe = (base + pd.offsets.QuarterEnd() * i).strftime("%Y-%m-%d")
        rows.append({"period_end": pe, "Revenue": rev, "OperatingIncome": opi,
                     "GrossProfit": gp, "IncomeAfterTaxes": ni, "PreTaxIncome": ni * 1.1})
    return _fin(rows)


def _balance(periods: list[str], *, ta=1000.0, ca=400.0, cl=200.0, cap=100.0, ltd=50.0) -> pd.DataFrame:
    rows = []
    for pe in periods:
        rows.append({"period_end": pe,
                     "raw_json": json.dumps([
                         {"type": "TotalLiabilitiesEquity", "value": ta},
                         {"type": "CurrentAssets", "value": ca},
                         {"type": "CurrentLiabilities", "value": cl},
                         {"type": "CapitalStock", "value": cap},
                         {"type": "LongtermBorrowings", "value": ltd},
                     ])})
    return pd.DataFrame(rows)


def test_durable_high_quality_scores_high():
    inc = _income(12, rev=100, opi=30, gp=55, ni=28)          # stable 30% op margin, purity 30/28>1
    bs = _balance(["2021-09-30", "2021-12-31"])
    fin_metrics = {"roe": 0.25, "ttm_eps": 5.0, "latest_fy_eps": 4.0, "annual_eps": [2.0, 3.0, 4.0]}
    detail = {"foreign_net_5": [10, 5, 8, 12, 3], "trust_net_5": [4, 2, 1, 5, 2]}
    res = compute_durability(fin_metrics=fin_metrics, detail=detail, financials=inc, balance_sheet=bs, params=PARAMS)
    assert res.score >= 60
    assert res.missing == ["cfo_quality"]                     # all but CFO (no cash flow passed)
    assert res.components["op_margin_stability"] > 0.9        # zero CV -> ~1.0
    assert res.components["earnings_purity"] == 1.0           # operating drives net income
    assert res.fscore is not None


def test_cfo_quality_and_full_fscore_with_cash_flow():
    inc = _income(12, rev=100, opi=30, gp=55, ni=28)          # FY2021 NI = 4*28 = 112
    bs = _balance(["2021-09-30", "2021-12-31"])
    cash_flow = pd.DataFrame([{"period_end": "2021-12-31", "cfo": 150.0}])   # CFO/NI = 150/112 > 1
    res = compute_durability(fin_metrics={"roe": 0.25, "annual_eps": [2.0, 3.0, 4.0]},
                             detail={}, financials=inc, balance_sheet=bs, params=PARAMS, cash_flow=cash_flow)
    assert "cfo_quality" not in res.missing
    assert res.components["cfo_quality"] == 1.0               # CFO comfortably exceeds NI
    assert res.fscore is not None                              # now includes the 2 cash-flow points

    # Low cash conversion (CFO << NI) -> earnings-quality warning.
    weak_cf = pd.DataFrame([{"period_end": "2021-12-31", "cfo": 30.0}])      # 30/112 < floor 0.5
    res2 = compute_durability(fin_metrics={"roe": 0.25}, detail={}, financials=inc,
                              balance_sheet=bs, params=PARAMS, cash_flow=weak_cf)
    assert res2.components["cfo_quality"] == 0.0


def test_non_operating_driven_earnings_low_purity():
    # Operating income tiny, net income large (業外/one-off-driven) -> purity collapses.
    inc = _income(12, rev=100, opi=10, gp=55, ni=50)          # OPI/NI = 0.2 < purity_floor 0.5
    bs = _balance(["2021-09-30", "2021-12-31"])
    res = compute_durability(fin_metrics={"roe": 0.25}, detail={}, financials=inc, balance_sheet=bs, params=PARAMS)
    assert res.components["earnings_purity"] == 0.0


def test_volatile_margin_scores_low_stability():
    base = pd.Timestamp("2019-03-31")
    rows = []
    swing = [0.40, 0.05, 0.45, 0.02, 0.38, 0.06, 0.50, 0.01, 0.42, 0.03, 0.40, 0.04]
    for i, m in enumerate(swing):
        pe = (base + pd.offsets.QuarterEnd() * i).strftime("%Y-%m-%d")
        rows.append({"period_end": pe, "Revenue": 100.0, "OperatingIncome": 100.0 * m,
                     "GrossProfit": 55.0, "IncomeAfterTaxes": 28.0, "PreTaxIncome": 30.0})
    inc = _fin(rows)
    res = compute_durability(fin_metrics={}, detail={}, financials=inc, balance_sheet=None, params=PARAMS)
    assert res.components["op_margin_stability"] < 0.4        # high CV -> low stability


def test_missing_data_omits_components_not_fabricates():
    # Only ROE + annual EPS available; no financial frames -> margin/purity/fscore omitted.
    res = compute_durability(
        fin_metrics={"roe": 0.18, "annual_eps": [1.0, 1.2, 1.5]},
        detail={}, financials=None, balance_sheet=None, params=PARAMS,
    )
    assert "op_margin_stability" in res.missing
    assert "earnings_purity" in res.missing
    assert "partial_fscore" in res.missing
    assert "roe_quality" in res.components and "multiyear_consistency" in res.components
    assert 0 <= res.score <= 100


def test_no_action_language_is_irrelevant_score_only():
    res = compute_durability(fin_metrics={}, detail={}, financials=None, balance_sheet=None, params=PARAMS)
    assert res.score == 0 and res.components == {}            # nothing computable -> 0, no crash
