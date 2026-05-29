from __future__ import annotations

from backend.app.services.strategy.canslim.news_pillar import NPillarAnalysis, NPillarClaim
from backend.app.services.strategy.canslim.params import load_params
from backend.app.services.strategy.canslim.pillar_screening import (
    assemble_pillars,
    screen_A,
    screen_C,
    screen_I,
    screen_L,
    screen_M,
    screen_N,
    screen_S,
)
from backend.app.services.strategy.canslim.screening import build_screening_result, contains_forbidden_action_language
from backend.app.services.strategy.canslim.screening_language import clean_user_facing_text
from backend.app.services.strategy.canslim.types import HorizonObservation, MarketFeatures, RuleResult
from backend.app.services.strategy.canslim.features import CanslimFeatures


def _features(**overrides) -> CanslimFeatures:
    data = {
        "symbol": "2330",
        "as_of_date": "2026-01-02",
        "quarterly_eps_yoy": 0.3,
        "eps_cagr_3y": 0.3,
        "roe_ttm": 0.2,
        "close": 98.0,
        "high_252d": 100.0,
        "rs_60d_pct": 0.8,
        "rs_252d_pct": 0.8,
        "ma20": 95.0,
        "ma60": 90.0,
        "ma120": 80.0,
        "ma120_slope": 0.01,
        "avg_turnover_20": 50_000_000,
        "up_down_volume_ratio_10": 1.5,
        "foreign_net_5": [1, 1, 1, 1, 1],
        "trust_net_5": [1, 1, 1, 1, 1],
    }
    data.update(overrides)
    return CanslimFeatures(**data)


def _params():
    return load_params()


def test_c_pillar_pass_fail_insufficient_from_yaml_bands():
    params = _params()
    c = params["screening"]["C"]
    assert screen_C(_features(quarterly_eps_yoy=float(c["c_pass"])), {}, params).status == "Pass"
    weak_supported = screen_C(
        _features(quarterly_eps_yoy=float(c["c_weak"]) + 0.01),
        {"G-1": RuleResult("G-1", True)},
        params,
    )
    assert weak_supported.status == "Weak"
    assert "weak EPS band" in weak_supported.reason
    assert screen_C(_features(quarterly_eps_yoy=float(c["c_weak"]) - 0.01), {}, params).status == "Fail"
    assert screen_C(_features(quarterly_eps_yoy=None), {}, params).status == "Insufficient_Data"


def test_a_pillar_pass_fail_insufficient_from_yaml_bands():
    params = _params()
    a = params["screening"]["A"]
    assert screen_A(_features(eps_cagr_3y=float(a["a_cagr_pass"]), roe_ttm=float(a["a_roe_pass"])), {}, params).status == "Pass"
    assert screen_A(_features(eps_cagr_3y=float(a["a_cagr_weak"]) - 0.01, roe_ttm=float(a["a_roe_fail"]) - 0.01), {}, params).status == "Fail"
    # CAGR undefined (loss base) but ROE present -> judged on ROE, not hidden as missing
    assert screen_A(_features(eps_cagr_3y=None, roe_ttm=float(a["a_roe_pass"])), {}, params).status == "Pass"
    assert screen_A(_features(eps_cagr_3y=None, roe_ttm=float(a["a_roe_fail"]) - 0.01), {}, params).status == "Fail"
    # CAGR undefined AND ROE unavailable -> genuinely insufficient
    assert screen_A(_features(eps_cagr_3y=None, roe_ttm=None), {}, params).status == "Insufficient_Data"


def test_a_pillar_ttm_below_fy_caps_pass_to_weak():
    params = _params()
    a = params["screening"]["A"]
    base = dict(eps_cagr_3y=float(a["a_cagr_pass"]), roe_ttm=float(a["a_roe_pass"]))
    # Would Pass on CAGR+ROE, but TTM EPS slipped below last full fiscal year -> Weak
    capped = screen_A(_features(**base, ttm_eps=4.0, latest_fy_eps=6.0), {}, params)
    assert capped.status == "Weak"
    assert any("TTM EPS below" in w for w in capped.data_warnings)
    # TTM EPS at/above last FY -> guard does not apply, stays Pass
    assert screen_A(_features(**base, ttm_eps=7.0, latest_fy_eps=6.0), {}, params).status == "Pass"
    # Guard never applies when the inputs are missing
    assert screen_A(_features(**base), {}, params).status == "Pass"


def test_c_pillar_surfaces_margin_expansion_driver():
    params = _params()
    c = params["screening"]["C"]
    expanding = screen_C(_features(quarterly_eps_yoy=float(c["c_pass"]), op_margin_last4=[0.10, 0.11, 0.12, 0.20]), {}, params)
    assert expanding.status == "Pass"
    assert any("op-margin expanding" in d for d in expanding.drivers)
    flat = screen_C(_features(quarterly_eps_yoy=float(c["c_pass"]), op_margin_last4=[0.20, 0.18, 0.16, 0.10]), {}, params)
    assert not any("op-margin expanding" in d for d in flat.drivers)


def test_n_pillar_price_floor_excludes_low_price():
    params = _params()
    low = screen_N(_features(close=8.0, high_252d=100.0), {}, params, n_pillar_analysis=None)
    assert low.status == "Fail"
    assert any("price floor" in w for w in low.data_warnings)


def test_n_pillar_hybrid_pass_ai_review_and_fail():
    params = _params()
    evidence = NPillarAnalysis(
        evidence="found",
        confidence="moderate",
        summary="sourced catalyst exists",
        claims=[NPillarClaim(source_url="https://example.com/n", published_date="2026-01-02", summary="new product progress")],
    )
    assert screen_N(_features(), {"T-2": RuleResult("T-2", True)}, params, n_pillar_analysis=evidence).status == "Pass"
    assert screen_N(_features(close=None), {}, params, n_pillar_analysis=None).status == "AI_Review_Required"
    assert screen_N(_features(close=80.0, high_252d=100.0), {}, params, n_pillar_analysis=None).status == "Fail"


def test_s_pillar_warns_unavailable_chip_data_and_bands():
    params = _params()
    verdict = screen_S(_features(), {}, params)
    assert verdict.status == "Pass"
    assert any("day_trade_ratio unavailable" in item for item in verdict.data_warnings)
    assert any("chip_concentration unavailable" in item for item in verdict.data_warnings)
    assert screen_S(_features(avg_turnover_20=1), {}, params).status == "Fail"
    assert screen_S(_features(avg_turnover_20=None), {}, params).status == "Insufficient_Data"


def test_l_pillar_pass_fail_insufficient_from_yaml_bands():
    params = _params()
    l = params["screening"]["L"]
    assert screen_L(_features(rs_60d_pct=float(l["l_rs_pass"]), rs_252d_pct=float(l["l_rs_pass"])), {"T-3": RuleResult("T-3", True)}, params).status == "Pass"
    assert screen_L(_features(rs_60d_pct=float(l["l_rs_pass"]), rs_252d_pct=float(l["l_rs_fail"]) - 0.01), {"T-3": RuleResult("T-3", True)}, params).status == "Fail"
    assert screen_L(_features(rs_60d_pct=float(l["l_rs_pass"]), rs_252d_pct=None), {"T-3": RuleResult("T-3", True)}, params).status == "Insufficient_Data"
    assert screen_L(_features(rs_60d_pct=None), {}, params).status == "Insufficient_Data"


def test_i_pillar_pass_fail_insufficient():
    params = _params()
    assert screen_I(_features(), {}, params).status == "Pass"
    assert screen_I(_features(foreign_net_5=[-1, -1, -1], trust_net_5=[-1, -1, -1]), {}, params).status == "Fail"
    flat = screen_I(_features(foreign_net_5=[0, 1, -1], trust_net_5=[0, 0, 0]), {}, params)
    assert flat.status == "Weak"
    assert "flat/mixed" in flat.reason
    assert screen_I(_features(foreign_net_5=None), {}, params).status == "Insufficient_Data"


def test_screening_language_english_boundaries_do_not_mangle_compound_words():
    text = "shareholding buyback household buy sell hold target price"
    cleaned = clean_user_facing_text(text)
    assert "shareholding" in cleaned
    assert "buyback" in cleaned
    assert "household" in cleaned
    assert "watchlist" in cleaned
    assert "exit-pressure" in cleaned
    assert "carry" in cleaned
    assert "valuation reference" in cleaned


def test_m_pillar_regime_gate_statuses():
    params = _params()
    risk_on = MarketFeatures(taiex_close=100, taiex_ma150=90, taiex_ma150_slope=0.1, tpex_close=100, tpex_ma150=90, tpex_ma150_slope=0.1, breadth_above_ma60_pct=0.8)
    severe = MarketFeatures(taiex_close=80, taiex_ma150=90, taiex_ma150_slope=-0.1, tpex_close=80, tpex_ma150=90, tpex_ma150_slope=-0.1, breadth_above_ma60_pct=0.2)
    unknown = MarketFeatures()
    assert screen_M(risk_on, params).status == "Pass"
    assert screen_M(severe, params).status == "Fail"
    assert screen_M(unknown, params).status == "Insufficient_Data"


def test_assemble_pillars_returns_all_seven_and_is_verb_free():
    params = _params()
    market = MarketFeatures(taiex_close=100, taiex_ma150=90, taiex_ma150_slope=0.1, tpex_close=100, tpex_ma150=90, tpex_ma150_slope=0.1, breadth_above_ma60_pct=0.8)
    evidence = NPillarAnalysis(
        evidence="found",
        confidence="moderate",
        summary="sourced catalyst exists",
        claims=[NPillarClaim(source_url="https://example.com/n", published_date="2026-01-02", summary="new product progress")],
    )
    verdicts = assemble_pillars(features=_features(), rule_results={}, market=market, params=params, n_pillar_analysis=evidence)
    assert set(verdicts) == {"C", "A", "N", "S", "L", "I", "M"}
    assert not contains_forbidden_action_language({k: v.__dict__ for k, v in verdicts.items()})


def test_build_screening_result_consumes_assembled_pillars(monkeypatch):
    params = _params()
    monkeypatch.setattr("backend.app.services.strategy.canslim.screening.load_params", lambda: params)
    monkeypatch.setattr("backend.app.services.strategy.canslim.screening.build_market_features", lambda *args, **kwargs: MarketFeatures(taiex_close=100, taiex_ma150=90, taiex_ma150_slope=0.1, tpex_close=100, tpex_ma150=90, tpex_ma150_slope=0.1, breadth_above_ma60_pct=0.8))
    monkeypatch.setattr("backend.app.services.strategy.canslim.screening.observe", lambda *args, **kwargs: {"swing_term": HorizonObservation(
        horizon="swing_term",
        status="watching",
        direction_hint="up",
        evidence_based_reasons=[],
        triggered_rule_ids=["G-1", "G-2", "G-3", "G-4", "T-1", "T-3", "SD-1", "SD-2", "I-1", "I-2", "I-3", "M-1"],
        suitable_strategy_examples=[],
        key_observation_conditions=[],
        invalidation_signals=[],
        risk_level="moderate",
        confidence_level="high",
        scores={"grade": "A", "signal": 65, "risk": 20, "confidence": 80, "hard_blocked": False},
        data_warnings=[],
    )})
    result = build_screening_result("2330", "2026-01-02", store=object())
    assert result.canslim_match.endswith("/7")
    assert result.pillars["C"] == "Pass"
    assert result.pillars["M"] == "Pass"
    assert not contains_forbidden_action_language(result.model_dump())
