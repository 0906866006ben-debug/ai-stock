"""CAN SLIM screener-first result assembly.

This module reuses the validated `observe()` layer and only remaps its output
into a decision-support screening surface. It does not change CAN SLIM signal,
score, grade, rule, or market-regime logic.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

from backend.app.models.screener_schemas import Evidence, PillarStatus, ScreeningResult
from backend.app.services.strategy.canslim.features import CanslimFeatures, build_features
from backend.app.services.strategy.canslim.news_pillar import NPillarAnalysis, analyze_n_pillar_sources
from backend.app.services.strategy.canslim.pillar_screening import PillarVerdict, assemble_pillars
from backend.app.services.strategy.canslim.observer import observe
from backend.app.services.strategy.canslim.params import load_params
from backend.app.services.strategy.canslim.regime import build_market_features
from backend.app.services.strategy.canslim.rules_growth import GROWTH_RULES
from backend.app.services.strategy.canslim.rules_institutional import INSTITUTIONAL_RULES
from backend.app.services.strategy.canslim.rules_market import regime_severity
from backend.app.services.strategy.canslim.rules_supply import SUPPLY_RULES
from backend.app.services.strategy.canslim.rules_technical import TECHNICAL_RULES
from backend.app.services.strategy.canslim.screening_language import (
    FORBIDDEN_TERMS,
    clean_string_list,
    clean_user_facing_text,
    contains_forbidden_action_language,
)
from backend.app.services.strategy.canslim.types import HorizonObservation, MarketFeatures, RuleResult

PILLARS = ("C", "A", "N", "S", "L", "I", "M")
PILLAR_RULES = {
    "C": ("G-1", "G-2"),
    "A": ("G-3", "G-4", "G-5"),
    "S": ("SD-1", "SD-2", "SD-3", "SD-4"),
    "L": ("T-1", "T-2", "T-3", "T-4", "T-5"),
    "I": ("I-1", "I-2", "I-3", "I-4"),
    "M": ("M-1", "M-2", "M-3", "M-4"),
}


def build_screening_result(
    symbol: str,
    as_of_date: str,
    *,
    store=None,
    market=None,
    fin_metrics=None,
    detail=None,
    universe_returns_60d=None,
    universe_returns_252d=None,
    event_window_active=None,
    eps_filing_date=None,
    horizon: str = "swing_term",
    yahoo_news: list[dict[str, Any]] | None = None,
    tw_news_sentiment: list[dict[str, Any]] | None = None,
    calendar: list[dict[str, Any]] | dict[str, Any] | None = None,
    n_pillar_analysis: NPillarAnalysis | dict[str, Any] | None = None,
    universe_shares: dict[str, float] | None = None,
) -> ScreeningResult:
    """Build a verb-free CAN SLIM screening result from existing observations."""

    params = load_params()
    market_features = _market_features_first(as_of_date, market=market, store=store)
    market_regime = regime_severity(market_features, params) or "unknown"
    observations = observe(
        symbol,
        as_of_date,
        store=store,
        market=market_features,
        fin_metrics=fin_metrics,
        detail=detail,
        universe_returns_60d=universe_returns_60d,
        universe_returns_252d=universe_returns_252d,
        event_window_active=event_window_active,
        eps_filing_date=eps_filing_date,
    )
    card = observations.get(horizon) or observations["swing_term"]
    n_analysis = analyze_n_pillar_sources(
        yahoo_news=yahoo_news,
        tw_news_sentiment=tw_news_sentiment,
        calendar=calendar,
        ai_output=n_pillar_analysis,
    )
    features, rule_results = _features_and_rule_results(
        symbol,
        as_of_date,
        store=store,
        fin_metrics=fin_metrics,
        detail=detail,
        universe_returns_60d=universe_returns_60d,
        universe_returns_252d=universe_returns_252d,
        event_window_active=event_window_active,
        eps_filing_date=eps_filing_date,
        params=params,
        card=card,
    )
    pillar_verdicts = assemble_pillars(
        features=features,
        rule_results=rule_results,
        market=market_features,
        params=params,
        n_pillar_analysis=n_analysis,
        market_regime=market_regime,
        universe_shares=universe_shares,
    )
    pillars = {pillar: verdict.status for pillar, verdict in pillar_verdicts.items()}
    raw_grade = str(card.scores.get("grade", "C"))
    candidate_grade = _regime_adjusted_grade(raw_grade, market_regime)
    candidate_grade = _cap_grade_for_failed_fundamentals(candidate_grade, pillars)
    action_type = _action_type(candidate_grade, market_regime, pillars)
    warnings = _clean_strings([
        *market_features.data_warnings,
        *card.data_warnings,
        *n_analysis.data_warnings,
        *(warning for verdict in pillar_verdicts.values() for warning in verdict.data_warnings),
    ])
    needs_review = _manual_review_items(pillars, warnings)
    evidence = [*_evidence_from_card(card), *_evidence_from_n_pillar(n_analysis)]
    interpretation = _interpretation(candidate_grade, market_regime, pillars, card, pillar_verdicts)

    pillar_metrics = _pillar_metrics(features, market_features, market_regime)
    if n_analysis.catalyst_score is not None:
        types = [c.catalyst_type for c in n_analysis.claims if c.catalyst_type]
        top_type = f" · {types[0]}" if types else ""
        pillar_metrics["N"] = f"催化劑強度 {n_analysis.catalyst_score}/100{top_type}"

    return ScreeningResult(
        stock_id=str(symbol),
        as_of_date=str(as_of_date),
        candidate_grade=candidate_grade,  # type: ignore[arg-type]
        canslim_match=_canslim_match(pillars),
        pillars=pillars,
        pillar_metrics=pillar_metrics,
        n_catalyst_score=n_analysis.catalyst_score,
        scores={
            "signal": int(card.scores.get("signal", 0) or 0),
            "risk": int(card.scores.get("risk", 0) or 0),
            "confidence": int(card.scores.get("confidence", 0) or 0),
        },
        market_regime=market_regime,  # type: ignore[arg-type]
        interpretation=_safe_text(interpretation),
        evidence=evidence,
        data_warnings=warnings,
        needs_manual_review=needs_review,
        action_type=action_type,  # type: ignore[arg-type]
    )


def _features_and_rule_results(
    symbol: str,
    as_of_date: str,
    *,
    store,
    fin_metrics,
    detail,
    universe_returns_60d,
    universe_returns_252d,
    event_window_active,
    eps_filing_date,
    params,
    card: HorizonObservation,
) -> tuple[CanslimFeatures | None, dict[str, RuleResult]]:
    features: CanslimFeatures | None = None
    rule_results: dict[str, RuleResult] = {}
    try:
        if store is not None:
            features = build_features(
                symbol,
                as_of_date,
                store,
                universe_returns_60d=universe_returns_60d,
                universe_returns_252d=universe_returns_252d,
                fin_metrics=fin_metrics,
                detail=detail,
                eps_filing_date=eps_filing_date,
                event_window_active=event_window_active,
            )
            for evaluator in [*GROWTH_RULES, *TECHNICAL_RULES, *SUPPLY_RULES, *INSTITUTIONAL_RULES]:
                result = evaluator(features, params)
                rule_results[result.rule_id] = result
    except Exception:
        features = None
        rule_results = {}
    for rule_id in card.triggered_rule_ids:
        rule_results.setdefault(str(rule_id), RuleResult(rule_id=str(rule_id), triggered=True))
    for warning in card.data_warnings:
        token = _rule_id_from_warning(str(warning))
        if token and token not in rule_results:
            rule_results[token] = RuleResult(rule_id=token, triggered=False, data_warning=str(warning))
        elif not token:
            for inferred in _rule_ids_from_warning_text(str(warning)):
                rule_results.setdefault(inferred, RuleResult(rule_id=inferred, triggered=False, data_warning=str(warning)))
    return features, rule_results


def _rule_id_from_warning(value: str) -> str | None:
    match = re.search(r"\b(G|T|SD|I|M|R)-\d+", value)
    return match.group(0) if match else None


def _rule_ids_from_warning_text(value: str) -> list[str]:
    lowered = value.lower()
    out: list[str] = []
    if any(token in lowered for token in ("eps", "filing", "revenue")):
        out.extend(["G-2", "G-3"])
    if any(token in lowered for token in ("roe", "margin")):
        out.append("G-4")
    if any(token in lowered for token in ("foreign", "trust", "institution")):
        out.extend(["I-1", "I-2"])
    if any(token in lowered for token in ("taiex", "tpex", "breadth", "market", "index")):
        out.append("M-1")
    return out


def pillar_statuses(card: HorizonObservation, *, market_regime: str = "unknown") -> dict[str, PillarStatus]:
    triggered = set(card.triggered_rule_ids)
    warnings = list(card.data_warnings)
    statuses: dict[str, PillarStatus] = {}
    for pillar in PILLARS:
        if pillar == "N":
            statuses[pillar] = "AI_Review_Required"
            continue
        if _pillar_insufficient(pillar, warnings):
            statuses[pillar] = "Insufficient_Data"
            continue
        rules = PILLAR_RULES[pillar]
        count = sum(1 for rule_id in rules if rule_id in triggered)
        if pillar == "M":
            statuses[pillar] = _market_status(market_regime, count)
        elif count >= 2 or (len(rules) <= 2 and count == len(rules)):
            statuses[pillar] = "Pass"
        elif count == 1:
            statuses[pillar] = "Weak"
        else:
            statuses[pillar] = "Neutral"
    if bool(card.scores.get("hard_blocked", False)):
        for rule_id in card.scores.get("blocking_rule_ids", []) or []:
            pillar = _pillar_for_rule(str(rule_id))
            if pillar in statuses:
                statuses[pillar] = "Fail"
    return statuses


def _market_features_first(as_of_date: str, *, market, store) -> MarketFeatures:
    if isinstance(market, MarketFeatures):
        return market
    return build_market_features(as_of_date, index_bundle=market if isinstance(market, dict) else None, store=store)


def _market_status(regime: str, triggered_count: int) -> PillarStatus:
    if regime == "risk_on":
        return "Pass"
    if regime == "risk_off":
        return "Weak"
    if regime == "severe":
        return "Fail"
    return "Weak" if triggered_count else "Insufficient_Data"


def _pillar_insufficient(pillar: str, warnings: Iterable[str]) -> bool:
    tokens = {
        "C": ("eps", "revenue", "filing"),
        "A": ("eps", "roe", "margin", "filing"),
        "S": ("volume", "turnover", "liquidity"),
        "L": ("relative", "52-week", "moving", "base"),
        "I": ("foreign", "trust", "institution"),
        "M": ("taiex", "tpex", "breadth", "market", "index"),
    }[pillar]
    text = " ".join(str(item).lower() for item in warnings)
    return any(token in text for token in tokens)


def _pillar_for_rule(rule_id: str) -> str | None:
    for pillar, rules in PILLAR_RULES.items():
        if rule_id in rules:
            return pillar
    return None


def _regime_adjusted_grade(raw_grade: str, regime: str) -> str:
    order = ["D", "C", "B", "A", "S"]
    grade = raw_grade if raw_grade in order else "C"
    idx = order.index(grade)
    if regime == "risk_off":
        idx -= 1
    elif regime == "severe":
        idx -= 2
    return order[max(0, idx)]


def _cap_grade_for_failed_fundamentals(grade: str, pillars: dict[str, PillarStatus]) -> str:
    """A CANSLIM candidate that fails BOTH growth pillars (C current earnings AND
    A annual quality) should not show a top grade just because its momentum/technical
    signal is decent. Cap the grade at C so it can't appear as S/A/B."""
    if pillars.get("C") == "Fail" and pillars.get("A") == "Fail":
        order = ["D", "C", "B", "A", "S"]
        if grade in order and order.index(grade) > order.index("C"):
            return "C"
    return grade


def _action_type(grade: str, regime: str, pillars: dict[str, PillarStatus]) -> str:
    if "Insufficient_Data" in pillars.values() or "AI_Review_Required" in pillars.values():
        if grade in {"S", "A", "B"} and regime == "risk_on" and pillars.get("N") == "AI_Review_Required":
            return "Manual Review Required"
    if regime in {"risk_off", "severe"}:
        return "Manual Review Required" if grade in {"S", "A", "B", "C"} else "Track Only"
    if grade in {"S", "A", "B"}:
        return "Watchlist Candidate"
    if grade == "C":
        return "Manual Review Required"
    return "Track Only"


def _manual_review_items(pillars: dict[str, PillarStatus], warnings: list[str]) -> list[str]:
    items = [f"{pillar} pillar requires source review" for pillar, status in pillars.items() if status == "AI_Review_Required"]
    items.extend(f"{pillar} pillar data gap" for pillar, status in pillars.items() if status == "Insufficient_Data")
    if warnings:
        items.append("data warnings present")
    return _clean_strings(items)


def _evidence_from_card(card: HorizonObservation) -> list[Evidence]:
    evidence: list[Evidence] = []
    for reason in card.evidence_based_reasons[:24]:
        pillar = _pillar_for_reason(reason)
        evidence.append(Evidence(pillar=pillar, source_url=None, published_date=None, summary=_safe_text(_humanize_reason(reason))))
    return evidence


_VALUE_RE = re.compile(r"([a-zA-Z_]\w*)=(-?\d+(?:\.\d+)?|True|False|\w+)")


def _humanize_reason(reason: str) -> str:
    """Translate a terse rule reason (e.g. ``M-1 taiex_close=..., ma150_slope=...``)
    into a plain-Chinese, verb-free description for the UI. Unknown rule ids fall
    back to the raw reason so nothing is silently dropped."""
    rid = re.match(r"\s*([A-Z]+-\d+)", reason)
    rule_id = rid.group(1) if rid else ""
    vals = dict(_VALUE_RE.findall(reason))

    def num(key: str) -> float | None:
        try:
            return float(vals[key])
        except (KeyError, ValueError, TypeError):
            return None

    def pct(v: float | None) -> str:
        return f"{v * 100:.0f}%" if v is not None else "—"

    def yi(v: float | None) -> str:
        if v is None:
            return "—"
        return f"{v / 1e8:,.0f} 億元" if abs(v) >= 1e8 else f"{v / 1e4:,.0f} 萬元"

    def mult(v: float | None) -> str:
        return f"{v:.1f} 倍" if v is not None else "—"

    if rule_id == "G-1":
        return f"月營收年增率維持成長（最新 {pct(num('latest'))}，前期 {pct(num('previous'))}）"
    if rule_id == "G-2":
        return f"單季 EPS 年增 {pct(num('quarterly_eps_yoy'))}"
    if rule_id == "G-3":
        return f"近三年 EPS 年複合成長 {pct(num('eps_cagr_3y'))}"
    if rule_id == "G-4":
        return f"近四季股東權益報酬率 ROE 為 {pct(num('roe_ttm'))}"
    if rule_id == "G-5":
        return f"營業利益率 {pct(num('op_margin_latest'))}，高於近期平均 {pct(num('prior_mean'))}"
    if rule_id == "T-1":
        return f"相對強弱（近60日）領先大盤，位於第 {pct(num('rs_60d_pct'))} 分位"
    if rule_id == "T-2":
        return f"股價接近一年高點（約為一年高點的 {pct(num('close_to_high_252d'))}）"
    if rule_id == "T-3":
        return "均線多頭排列，季線（120日）趨勢向上"
    if rule_id == "T-4":
        return f"站上近期盤整箱型上緣（箱型緊密度 {num('tightness'):.2f}）" if num("tightness") is not None else "站上近期盤整箱型上緣"
    if rule_id == "T-5":
        return f"成交量放大，約為均量的 {mult(num('volume_multiple'))}"
    if rule_id == "SD-1":
        if "avg_turnover_20" in vals:
            return f"20日均成交額 {yi(num('avg_turnover_20'))}，高於流動性門檻 {yi(num('liquidity_floor'))}"
        return f"流動性資料不足以判斷（門檻 {yi(num('liquidity_floor'))}）"
    if rule_id == "SD-2":
        return f"近10日上漲量能 / 下跌量能比為 {num('up_down_volume_ratio_10'):.2f}（大於 1 代表多方量能較強）" if num("up_down_volume_ratio_10") is not None else "上漲與下跌量能比偏多"
    if rule_id == "I-1":
        days = re.search(r"foreign_net_last_(\d+)_sum", reason)
        return f"外資近 {days.group(1) if days else ''} 日累積呈淨流入"
    if rule_id == "I-2":
        n = vals.get("trust_positive_days", "")
        return f"投信連續 {n} 日站在淨流入方"
    if rule_id == "I-3":
        return "外資與投信資金方向同步偏多"
    if rule_id == "M-1":
        if "regime_on_fail" in reason:
            return "大盤環境尚未達多頭條件"
        return "加權指數站上 150日均線且趨勢向上（多頭環境）"
    if rule_id == "M-2":
        if "disagreement" in reason:
            return "上市與上櫃指數走勢分歧"
        return "上櫃指數（TPEx）站上 150日均線且趨勢向上"
    if rule_id == "M-3":
        return f"市場廣度：約 {pct(num('breadth_above_ma60_pct'))} 個股站上 60日均線"
    if rule_id == "M-4":
        if "below_ma60" in reason:
            return "費城半導體與那斯達克皆在 60日均線之下，外圍環境偏弱"
        return "費城半導體與那斯達克偏多，外圍環境提供支撐"
    if rule_id == "R-1":
        v = num("close_to_ma20")
        return f"股價高於 20日均線約 {(v - 1) * 100:.0f}%，短線乖離偏大" if v is not None else "短線乖離 20日均線偏大"
    if rule_id == "R-2":
        return f"近期量能異常（近20日 / 前20日量比 {num('volume_ratio_recent_vs_prior_20'):.2f}）" if num("volume_ratio_recent_vs_prior_20") is not None else "近期量能出現異常"
    if rule_id == "R-3":
        return f"法人轉為淨流出（外資 {vals.get('foreign_seller_days', '')} 日、投信 {vals.get('trust_seller_days', '')} 日）"
    if rule_id == "R-4":
        return "接近財報或重大事件期間，波動風險升高"
    if rule_id == "R-5":
        return "大盤處於風險趨避（risk-off）狀態"
    if rule_id == "R-6":
        if "avg_turnover_20" in vals:
            return f"流動性偏低（20日均成交額 {yi(num('avg_turnover_20'))}，低於門檻 {yi(num('liquidity_floor'))}）"
        return f"流動性低於門檻 {yi(num('liquidity_floor'))}"
    if rule_id == "R-8":
        return f"本益比偏高（PE {num('pe_ttm'):.0f}），須留意評價風險" if num("pe_ttm") is not None else "本益比偏高，須留意評價風險"
    return reason


def _evidence_from_n_pillar(analysis: NPillarAnalysis) -> list[Evidence]:
    if analysis.evidence != "found":
        return []
    return [
        Evidence(
            pillar="N",
            source_url=claim.source_url,
            published_date=claim.published_date,
            summary=_safe_text(claim.summary),
            catalyst_type=claim.catalyst_type,
        )
        for claim in analysis.claims
    ]


def _pillar_for_reason(reason: str) -> str:
    match = re.search(r"\b([GMTIS]|SD|R)-\d+", reason)
    if not match:
        return "General"
    token = match.group(1)
    if token == "G":
        return "C/A"
    if token == "T":
        return "L"
    if token == "SD":
        return "S"
    if token == "I":
        return "I"
    if token == "M":
        return "M"
    return "Risk"


def _pillar_metrics(
    features: CanslimFeatures | None,
    market: MarketFeatures,
    market_regime: str,
) -> dict[str, str]:
    """Short, factual key-metric string per pillar for the UI tiles (no action verbs)."""
    out: dict[str, str] = {}

    def pct(value: float | None, *, signed: bool = True) -> str | None:
        if value is None:
            return None
        return f"{value * 100:+.0f}%" if signed else f"{value * 100:.0f}%"

    if features is not None:
        if features.quarterly_eps_yoy is not None:
            out["C"] = f"EPS YoY {pct(features.quarterly_eps_yoy)}"
        elif features.month_revenue_yoy:
            out["C"] = f"月營收 YoY {pct(features.month_revenue_yoy[-1])}"

        a_parts: list[str] = []
        if features.roe_ttm is not None:
            a_parts.append(f"ROE {pct(features.roe_ttm, signed=False)}")
        if features.eps_cagr_3y is not None:
            a_parts.append(f"3yCAGR {pct(features.eps_cagr_3y)}")
        if a_parts:
            out["A"] = " · ".join(a_parts)

        if features.pct_from_52w_high is not None:
            out["N"] = f"距52週高 {pct(features.pct_from_52w_high)}"

        if features.avg_turnover_20 is not None:
            out["S"] = f"日均額 {features.avg_turnover_20 / 1e8:.1f}億"

        l_parts: list[str] = []
        if features.rs_60d_pct is not None:
            l_parts.append(f"RS60 {pct(features.rs_60d_pct, signed=False)}")
        if features.rs_252d_pct is not None:
            l_parts.append(f"RS252 {pct(features.rs_252d_pct, signed=False)}")
        if l_parts:
            out["L"] = " · ".join(l_parts)

        if features.foreign_net_5 is not None or features.trust_net_5 is not None:
            f5 = sum(features.foreign_net_5[-5:]) if features.foreign_net_5 else 0
            t5 = sum(features.trust_net_5[-5:]) if features.trust_net_5 else 0
            # FinMind net is in shares; show as 萬張 (1 張 = 1000 shares).
            out["I"] = f"外資5日 {f5 / 1e7:+.1f}萬張 · 投信 {t5 / 1e7:+.1f}萬張"

    regime_label = {"risk_on": "Risk On", "risk_off": "Risk Off", "severe": "Severe"}.get(market_regime, "Unknown")
    breadth = market.breadth_above_ma60_pct
    out["M"] = f"{regime_label}" + (f" · 寬度 {breadth * 100:.0f}%" if breadth is not None else "")
    return {pillar: _safe_text(text) for pillar, text in out.items() if text}


def _canslim_match(pillars: dict[str, PillarStatus]) -> str:
    matched = sum(1 for status in pillars.values() if status == "Pass")
    return f"{matched}/7"


def _interpretation(
    grade: str,
    regime: str,
    pillars: dict[str, PillarStatus],
    card: HorizonObservation,
    verdicts: dict[str, PillarVerdict] | None = None,
) -> str:
    pass_count = sum(1 for status in pillars.values() if status == "Pass")
    weak_count = sum(1 for status in pillars.values() if status == "Weak")
    review_count = sum(1 for status in pillars.values() if status in {"AI_Review_Required", "Insufficient_Data"})
    fail_count = sum(1 for status in pillars.values() if status == "Fail")
    driver_text = ""
    if verdicts:
        focus = [f"{pillar}:{verdict.status}" for pillar, verdict in verdicts.items()]
        driver_text = " Pillar verdicts " + ", ".join(focus) + "."
    return (
        f"CANSLIM screen grade {grade}; regime {regime}; "
        f"{pass_count} pillars pass, {weak_count} weak, {fail_count} fail, {review_count} requiring review; "
        f"risk {card.risk_level}, confidence {card.confidence_level}.{driver_text}"
    )


def _safe_text(value: str) -> str:
    return clean_user_facing_text(value)


def _clean_strings(values: Iterable[str]) -> list[str]:
    return clean_string_list(values)
