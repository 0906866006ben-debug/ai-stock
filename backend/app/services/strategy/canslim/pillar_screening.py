"""Formal CANSLIM per-pillar screening verdicts.

This module is a screening surface on top of existing CANSLIM features, rule
outputs, and regime classification. It does not change signal/score math.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from backend.app.models.screener_schemas import PillarStatus
from backend.app.services.strategy.canslim.features import CanslimFeatures, _rank_percentile
from backend.app.services.strategy.canslim.news_pillar import NPillarAnalysis
from backend.app.services.strategy.canslim.rules_market import regime_severity
from backend.app.services.strategy.canslim.screening_language import clean_string_list, clean_user_facing_text
from backend.app.services.strategy.canslim.types import MarketFeatures, RuleResult


@dataclass(frozen=True)
class PillarVerdict:
    status: PillarStatus
    reason: str
    drivers: list[str] = field(default_factory=list)
    data_warnings: list[str] = field(default_factory=list)

    def safe(self) -> "PillarVerdict":
        return PillarVerdict(
            status=self.status,
            reason=clean_user_facing_text(self.reason),
            drivers=clean_string_list(self.drivers),
            data_warnings=clean_string_list(self.data_warnings),
        )


RuleMap = Mapping[str, RuleResult]
Params = Mapping[str, Any]


def assemble_pillars(
    *,
    features: CanslimFeatures | None,
    rule_results: RuleMap,
    market: MarketFeatures,
    params: Params,
    n_pillar_analysis: NPillarAnalysis | None = None,
    market_regime: str | None = None,
    universe_shares: Mapping[str, float] | None = None,
) -> dict[str, PillarVerdict]:
    verdicts = {
        "C": screen_C(features, rule_results, params),
        "A": screen_A(features, rule_results, params),
        "N": screen_N(features, rule_results, params, n_pillar_analysis=n_pillar_analysis),
        "S": screen_S(features, rule_results, params, universe_shares=universe_shares),
        "L": screen_L(features, rule_results, params),
        "I": screen_I(features, rule_results, params),
        "M": screen_M(market, params, market_regime=market_regime),
    }
    return {pillar: verdict.safe() for pillar, verdict in verdicts.items()}


def screen_C(features: CanslimFeatures | None, rule_results: RuleMap, params: Params) -> PillarVerdict:
    cfg = params["screening"]["C"]
    # quarterly EPS YoY is undefined when the year-ago quarter was a loss (negative
    # base) — that is NOT missing data. When it is unavailable, fall back to monthly
    # revenue evidence before declaring Insufficient.
    eps_unavailable = _has_warning(rule_results, "G-2") or features is None or features.quarterly_eps_yoy is None
    if eps_unavailable:
        drivers = _drivers(rule_results, "G-1", "G-2")
        if _triggered(rule_results, "G-2"):
            return PillarVerdict("Pass", "C quarterly EPS rule output triggered", drivers)
        if _triggered(rule_results, "G-1"):
            return PillarVerdict("Weak", "C revenue acceleration rule output triggered", drivers)
        rev = _latest_revenue_yoy(features)
        if rev is not None:
            weak_min = float(cfg.get("revenue_fallback_weak_min", 0.0))
            sustained = _revenue_sustained(features, cfg)
            warnings = ["quarterly EPS YoY unavailable (likely loss-base quarter); C judged on monthly revenue YoY"]
            # Rigour: a single positive month is not enough — require a meaningful YoY
            # AND sustained growth across recent months before granting Weak.
            if rev >= weak_min and sustained:
                return PillarVerdict("Weak", f"C month_revenue_yoy={rev:.4f} sustained; quarterly EPS YoY unavailable", drivers, warnings)
            why = "below growth floor" if rev < weak_min else "not sustained across recent months"
            return PillarVerdict("Fail", f"C month_revenue_yoy={rev:.4f} {why}; quarterly EPS YoY unavailable", drivers, warnings)
        return _insufficient("C", "quarterly EPS YoY unavailable and no monthly revenue signal", ["G-2"])
    value = float(features.quarterly_eps_yoy)
    drivers = _drivers(rule_results, "G-1", "G-2")
    # Report C-3: surface current-quarter operating-margin expansion vs the trailing
    # 4-quarter average as supporting evidence (transparency only; does not move the
    # EPS pass/fail bands or the validated signal score).
    if _margin_expanding(features):
        drivers.append("op-margin expanding (latest > TTM avg)")
    # O'Neil earnings-acceleration: report the trend as a driver; flag severe
    # deceleration so it can cap a Pass below (transparency-first).
    accel, decel_severe = _earnings_acceleration(features, cfg)
    if accel is True:
        drivers.append("earnings accelerating (latest YoY > prior quarter)")
    elif accel is False:
        drivers.append("earnings decelerating (latest YoY < prior quarter)")
    if value >= float(cfg["c_pass"]):
        if decel_severe:
            # Strong latest quarter but growth-rate more than halved vs the prior
            # quarter -> O'Neil deceleration warning. Cap to Weak, never a hard Fail.
            return PillarVerdict("Weak", f"C quarterly_eps_yoy={value:.4f} passes band but earnings sharply decelerating", drivers, ["earnings-growth rate sharply decelerating (O'Neil C accel guard)"])
        return PillarVerdict("Pass", f"C quarterly_eps_yoy={value:.4f} meets pass band", drivers)
    if value >= float(cfg["c_weak"]):
        if _triggered(rule_results, "G-1"):
            return PillarVerdict("Weak", f"C quarterly_eps_yoy={value:.4f} weak EPS band with revenue-acceleration support", drivers)
        return PillarVerdict("Weak", f"C quarterly_eps_yoy={value:.4f} in weak band", drivers)
    return PillarVerdict("Fail", f"C quarterly_eps_yoy={value:.4f} below weak band", drivers)


def screen_A(features: CanslimFeatures | None, rule_results: RuleMap, params: Params) -> PillarVerdict:
    cfg = params["screening"]["A"]
    verdict = _screen_a_core(features, rule_results, params)
    if verdict.status != "Pass":
        return verdict
    # O'Neil trend guard: TTM EPS must hold at/above the last full fiscal-year EPS.
    # If it has slipped below, annual-earnings quality is decelerating, so A is capped
    # at Weak even when the CAGR/ROE bands passed. Never a hard Fail (anti-zero-signal).
    if (
        features is not None
        and features.ttm_eps is not None
        and features.latest_fy_eps is not None
        and features.ttm_eps < features.latest_fy_eps
    ):
        return PillarVerdict(
            "Weak",
            f"A capped to Weak: ttm_eps={features.ttm_eps:.2f} < latest_fy_eps={features.latest_fy_eps:.2f} (annual earnings decelerating)",
            verdict.drivers,
            [*verdict.data_warnings, "TTM EPS below last full fiscal-year EPS (O'Neil annual-trend guard)"],
        )
    # Stability guard: a strong endpoint CAGR can hide a mid-period collapse. If any
    # year-over-year step fell below the floor, annual growth is not steady -> cap to
    # Weak (transparency only; never a hard Fail).
    unstable, note = _annual_eps_unstable(features, cfg)
    if unstable:
        return PillarVerdict(
            "Weak",
            f"A capped to Weak: {note}",
            verdict.drivers,
            [*verdict.data_warnings, "annual EPS not steadily growing (stability guard)"],
        )
    return verdict


def _screen_a_core(features: CanslimFeatures | None, rule_results: RuleMap, params: Params) -> PillarVerdict:
    cfg = params["screening"]["A"]
    # Only annual EPS growth (G-3) is a hard requirement. ROE (G-4) frequently has
    # no source (needs balance-sheet equity), so it must NOT force Insufficient.
    # 3-year EPS CAGR is undefined when a base/end year had a loss (negative/zero
    # EPS) — that is NOT missing data. When CAGR is unavailable, judge A on ROE if we
    # have it (or the annual-growth rule), instead of hiding the stock as Insufficient.
    cagr_unavailable = _has_warning(rule_results, "G-3") or features is None or features.eps_cagr_3y is None
    if cagr_unavailable:
        roe_val = features.roe_ttm if features is not None else None
        drivers = _drivers(rule_results, "G-3", "G-4", "G-5")
        if roe_val is not None:
            roe = float(roe_val)
            warnings = ["3-year EPS CAGR unavailable (likely loss/zero base year); A judged on ROE"]
            if roe >= float(cfg["a_roe_pass"]):
                return PillarVerdict("Pass", f"A roe_ttm={roe:.4f}; eps_cagr_3y unavailable", drivers, warnings)
            if roe < float(cfg["a_roe_fail"]):
                return PillarVerdict("Fail", f"A roe_ttm={roe:.4f} below quality floor; eps_cagr_3y unavailable", drivers, warnings)
            return PillarVerdict("Weak", f"A roe_ttm={roe:.4f} mid-band; eps_cagr_3y unavailable", drivers, warnings)
        if features is not None and _triggered(rule_results, "G-3"):
            return PillarVerdict("Weak", "A annual growth rule triggered; magnitude unavailable", drivers)
        return _insufficient("A", "annual EPS CAGR unavailable and ROE unavailable", ["G-3"])

    cagr = float(features.eps_cagr_3y)
    drivers = [*_drivers(rule_results, "G-3", "G-4", "G-5"), "cyclical caveat: semiconductors may need cycle context"]
    warnings: list[str] = []
    cagr_pass = cagr >= float(cfg["a_cagr_pass"])
    cagr_fail = cagr < float(cfg["a_cagr_weak"])

    if features.roe_ttm is not None:
        roe = float(features.roe_ttm)
        quality_pass = roe >= float(cfg["a_roe_pass"])
        quality_fail = roe < float(cfg["a_roe_fail"])
        quality_desc = f"roe_ttm={roe:.4f}"
    else:
        # ROE needs a balance-sheet (equity) source we don't have. Judge A on the EPS
        # CAGR we CAN verify; treat the operating-margin trend only as a note. A strong
        # multi-year CAGR is itself quality evidence and must not be downgraded by a
        # thin-margin-business's small margin dip (e.g. server ODMs at ~6% op margin).
        margin_note = "margin↑" if _triggered(rule_results, "G-5") else "margin~/↓"
        warnings.append("ROE unavailable (needs balance-sheet equity source); A judged on EPS CAGR, operating-margin trend as note")
        quality_pass = cagr_pass  # growth is the verifiable quality signal when ROE is absent
        quality_fail = False
        quality_desc = f"roe_unavailable;cagr-led;{margin_note}"

    if cagr_pass and quality_pass:
        return PillarVerdict("Pass", f"A eps_cagr_3y={cagr:.4f}, {quality_desc} meet pass bands", drivers, warnings)
    if cagr_fail or quality_fail:
        return PillarVerdict("Fail", f"A eps_cagr_3y={cagr:.4f}, {quality_desc} below screening floor", drivers, warnings)
    return PillarVerdict("Weak", f"A eps_cagr_3y={cagr:.4f}, {quality_desc} partially meet bands", drivers, warnings)


def screen_N(
    features: CanslimFeatures | None,
    rule_results: RuleMap,
    params: Params,
    *,
    n_pillar_analysis: NPillarAnalysis | None,
) -> PillarVerdict:
    cfg = params["screening"]["N"]
    # O'Neil N listing filter: exclude very low-priced names (TW proxy for
    # 全額交割/警示股, which a true disposition-status feed would flag directly).
    price_floor = float(cfg.get("price_floor_twd", 0) or 0)
    if features is not None and features.close is not None and price_floor > 0 and float(features.close) < price_floor:
        return PillarVerdict(
            "Fail",
            f"N close={float(features.close):.2f} below price floor {price_floor:.0f} (likely 全額交割/警示股)",
            _drivers(rule_results, "T-2", "T-4", "T-5"),
            ["below price floor — likely 全額交割/警示股; O'Neil N listing filter"],
        )
    # Hybrid N: the quantifiable new-high (price proximity to the 52-week high) is the
    # BACKBONE and can Pass on its own — it is always available and is the validated
    # edge. The AI catalyst_score (0-100, from news_pillar) is a graded MODIFIER that
    # can upgrade a near-breakout; news alone never rescues a stock far from its high.
    catalyst_found = n_pillar_analysis is not None and n_pillar_analysis.evidence == "found" and bool(n_pillar_analysis.claims)
    score = int(n_pillar_analysis.catalyst_score) if (n_pillar_analysis and n_pillar_analysis.catalyst_score is not None) else 0
    catalyst_strong = score >= int(cfg.get("catalyst_strong_min", 60))
    catalyst_present = score >= int(cfg.get("catalyst_present_min", 30))
    warnings = list(n_pillar_analysis.data_warnings if n_pillar_analysis else [])
    drivers = _drivers(rule_results, "T-2", "T-4", "T-5")
    if catalyst_found:
        drivers.append(f"AI catalyst_score={score}/100 (claims={len(n_pillar_analysis.claims)})")

    if features is None or features.close is None or features.high_252d in {None, 0}:
        # Can't verify the new-high backbone. A strong AI catalyst alone is only Weak
        # (never Pass — Pass requires the price confirmation we can't see here).
        if catalyst_strong:
            return PillarVerdict("Weak", f"N AI catalyst_score={score} strong; 52-week high proximity unavailable", drivers, warnings)
        return PillarVerdict("AI_Review_Required", "N 52-week high proximity unavailable; no strong catalyst", drivers, warnings)

    close_to_high = float(features.close) / float(features.high_252d)
    near_pass = close_to_high >= float(cfg["close_to_high_pass"])
    near_weak = close_to_high >= float(cfg["close_to_high_weak"])

    if near_pass:
        # At/near a new high: passes on price strength alone; catalyst is a bonus note.
        note = f", AI catalyst_score={score}" if catalyst_present else ""
        return PillarVerdict("Pass", f"N close_to_high_252d={close_to_high:.4f} at/near 52-week high{note}", drivers, warnings)
    if near_weak:
        # Close but not quite — a strong AI-verified catalyst upgrades it to Pass.
        if catalyst_strong:
            return PillarVerdict("Pass", f"N close_to_high_252d={close_to_high:.4f} near high, strong AI catalyst_score={score}", drivers, warnings)
        return PillarVerdict("Weak", f"N close_to_high_252d={close_to_high:.4f} near 52-week high; catalyst_score={score}", drivers, warnings)
    # Far from the high: news cannot rescue N (extension is the real signal).
    detail = f"; AI catalyst_score={score} noted but price far from high" if catalyst_present else ""
    return PillarVerdict("Fail", f"N close_to_high_252d={close_to_high:.4f} far from 52-week high{detail}", drivers, warnings)


def screen_S(
    features: CanslimFeatures | None,
    rule_results: RuleMap,
    params: Params,
    *,
    universe_shares: Mapping[str, float] | None = None,
) -> PillarVerdict:
    """S verdict + cross-sectional supply (float-size) modifier (O'Neil D).

    The float modifier is a SCREENING-layer overlay only (it never touches the signal
    score/grade): small float = supply bonus (driver note); bloated mega-float (top
    decile of the universe) caps a Pass to Weak. Applied only when a universe shares
    map is supplied AND this symbol has shares data — otherwise a graceful no-op."""
    verdict = _screen_s_core(features, rule_results, params)
    if features is None or features.shares_outstanding is None or not universe_shares:
        return verdict
    cfg = params["screening"]["S"]
    pct = _rank_percentile(features.symbol, dict(universe_shares))
    if pct is None:
        return verdict
    mega_min = float(cfg.get("float_mega_pct_min", 1.01))   # >1 disables if unset
    small_max = float(cfg.get("float_small_pct_max", 0.0))
    if pct <= small_max:
        return PillarVerdict(
            verdict.status,
            f"{verdict.reason}; small float (size pct={pct:.2f})",
            [*verdict.drivers, f"small-float supply bonus (float size percentile={pct:.2f})"],
            verdict.data_warnings,
        )
    if pct >= mega_min and verdict.status == "Pass":
        return PillarVerdict(
            "Weak",
            f"{verdict.reason}; capped: bloated float (size pct={pct:.2f})",
            verdict.drivers,
            [*verdict.data_warnings, f"very large share float (size percentile={pct:.2f}) — diluted supply, O'Neil S"],
        )
    return verdict


def _screen_s_core(features: CanslimFeatures | None, rule_results: RuleMap, params: Params) -> PillarVerdict:
    cfg = params["screening"]["S"]
    warnings = [
        "day_trade_ratio unavailable - S pillar is partial",
        "chip_concentration unavailable - S pillar is partial",
    ]
    # TW ±10% price-limit awareness (transparency only — does not change the verdict).
    if features is not None and features.at_limit_up:
        warnings.append("漲停鎖死 (limit-up): cannot fill a market entry today — chase risk, not an entry")
    if features is not None and features.at_limit_down:
        warnings.append("跌停鎖死 (limit-down): exit liquidity gone — elevated downside risk")
    if features is None or features.avg_turnover_20 is None:
        if _triggered(rule_results, "SD-1") and _triggered(rule_results, "SD-2"):
            return PillarVerdict("Pass", "S liquidity and up-day volume rule outputs triggered", _drivers(rule_results, "SD-1", "SD-2", "SD-3", "SD-4"), warnings)
        if _triggered(rule_results, "SD-1"):
            return PillarVerdict("Weak", "S liquidity rule output triggered; volume expansion not confirmed", _drivers(rule_results, "SD-1", "SD-2", "SD-3", "SD-4"), warnings)
        return _insufficient("S", "liquidity data missing", ["SD-1"], warnings)
    turnover = float(features.avg_turnover_20)
    drivers = _drivers(rule_results, "SD-1", "SD-2", "SD-3", "SD-4")
    if turnover < float(cfg["liquidity_floor_twd"]):
        return PillarVerdict("Fail", f"S avg_turnover_20={turnover:.0f} below liquidity floor", drivers, warnings)

    # S1: overheating / blow-off guard — extreme volume spike while pinned near the
    # 52-week high is speculative, not a healthy breakout. Cap to Weak + raise risk.
    overheated, note = _overheated(features, cfg)
    if overheated:
        return PillarVerdict("Weak", f"S overheated: {note}", drivers, [*warnings, "possible blow-off/speculative volume spike — elevated risk"])

    up_down_ok = (
        features.up_down_volume_ratio_10 is not None
        and float(features.up_down_volume_ratio_10) >= float(cfg["up_down_volume_ratio_pass"])
    )
    # S2: a Pass needs up-day volume dominance AND volume that is not contracting.
    # Contraction is only counted when we actually have the data (missing -> no penalty).
    contracting_floor = float(cfg.get("volume_contracting_at_or_below", 1.0))
    expansion = features.volume_ratio_recent_vs_prior_20
    contracting = expansion is not None and float(expansion) <= contracting_floor
    if up_down_ok and not contracting:
        return PillarVerdict("Pass", f"S liquidity met, up_down_volume_ratio_10={features.up_down_volume_ratio_10:.4f}, volume not contracting", drivers, warnings)
    if up_down_ok and contracting:
        return PillarVerdict("Weak", f"S up-day volume dominant but overall volume contracting (上漲量縮) ratio={float(expansion):.2f}", drivers, warnings)
    return PillarVerdict("Weak", "S liquidity floor met; up-day volume expansion not confirmed", drivers, warnings)


def screen_L(features: CanslimFeatures | None, rule_results: RuleMap, params: Params) -> PillarVerdict:
    cfg = params["screening"]["L"]
    if features is None or features.rs_252d_pct is None:
        warnings = ["annual relative strength history missing"]
        return PillarVerdict("Insufficient_Data", "L annual relative strength history missing", _drivers(rule_results, "T-1", "T-3"), warnings)
    if features.rs_60d_pct is None:
        return PillarVerdict("Insufficient_Data", "L 60-day relative strength history missing", _drivers(rule_results, "T-1", "T-3"), ["60-day relative strength history missing"])
    rs_60 = float(features.rs_60d_pct)
    rs_252 = float(features.rs_252d_pct)
    stage2 = _triggered(rule_results, "T-3") or _stage2(features)
    drivers = _drivers(rule_results, "T-1", "T-3")
    if rs_60 >= float(cfg["l_rs_pass"]) and rs_252 >= float(cfg["l_rs_pass"]) and stage2:
        return PillarVerdict("Pass", f"L rs_60d_pct={rs_60:.4f}, rs_252d_pct={rs_252:.4f}, stage-2 alignment present", drivers)
    if rs_252 < float(cfg["l_rs_fail"]) or rs_60 < float(cfg["l_rs_fail"]):
        return PillarVerdict("Fail", f"L rs_60d_pct={rs_60:.4f}, rs_252d_pct={rs_252:.4f} below leader floor", drivers)
    return PillarVerdict("Weak", f"L rs_60d_pct={rs_60:.4f}, rs_252d_pct={rs_252:.4f}; stage2={stage2}", drivers)


def screen_I(features: CanslimFeatures | None, rule_results: RuleMap, params: Params) -> PillarVerdict:
    # Deliberate TW adaptation: O'Neil's I is institutional OWNERSHIP (rising fund
    # count). TW has no timely 13F-style ownership feed, so I is measured as recent
    # three-major-investors (三大法人) net-buy FLOW + strength — a faithful TW proxy,
    # not O'Neil's count metric.
    cfg = params["screening"]["I"]
    days = int(cfg["net_buy_days_min"])
    if _has_warning(rule_results, "I-1") or _has_warning(rule_results, "I-2"):
        return _insufficient("I", "institutional flow data missing", ["I-1", "I-2", "I-3"], [_warning_text(rule_results, "I-1"), _warning_text(rule_results, "I-2")])
    if features is None or features.foreign_net_5 is None or features.trust_net_5 is None:
        if _triggered(rule_results, "I-3"):
            return PillarVerdict("Pass", "I aligned institutional rule output triggered", _drivers(rule_results, "I-1", "I-2", "I-3"))
        if _triggered(rule_results, "I-1") or _triggered(rule_results, "I-2"):
            return PillarVerdict("Weak", "I one institutional rule output triggered", _drivers(rule_results, "I-1", "I-2", "I-3"))
        return _insufficient("I", "institutional flow data missing", ["I-1", "I-2", "I-3"])
    # Judge on the WINDOW's cumulative net buy (robust) plus its STRENGTH, rather than
    # demanding strictly-consecutive positive days (which 投信's frequent 0-days made
    # near-impossible -> a zero-signal trap). Consecutive-day counts are kept only as a
    # driver note ("連買").
    f_sum = sum(features.foreign_net_5[-days:])
    t_sum = sum(features.trust_net_5[-days:])
    foreign_positive = f_sum > 0
    trust_positive = t_sum > 0
    drivers = _drivers(rule_results, "I-1", "I-2", "I-3", "I-4")
    drivers.append(f"net-buy days foreign={_positive_days(features.foreign_net_5[-days:])}/{days}, trust={_positive_days(features.trust_net_5[-days:])}/{days}")

    # Strength = cumulative net buy / 20d avg volume. A full Pass needs both groups
    # accumulating AND meaningful combined size; light accumulation stays Weak. When
    # avg volume is unavailable, strength is not assessed (no penalty).
    strength_min = float(cfg.get("net_buy_strength_min", 0.0))
    f_str = _net_strength(features.foreign_net_5, features.avg_volume_20)
    t_str = _net_strength(features.trust_net_5, features.avg_volume_20)
    assessable = f_str is not None or t_str is not None
    combined = sum(s for s in (f_str, t_str) if s is not None)
    strong = assessable and combined >= strength_min
    if assessable:
        drivers.append(f"net-buy strength foreign={_fmt(f_str)}, trust={_fmt(t_str)} (x20d-vol)")

    # Most TW stocks have 投信=0, so requiring BOTH groups positive is a zero-signal
    # trap. A Pass needs net institutional accumulation with meaningful strength AND
    # no group actively distributing (trust=0 is fine; trust selling is not).
    no_distribution = f_sum >= 0 and t_sum >= 0
    net_accumulating = (f_sum + t_sum) > 0
    if no_distribution and net_accumulating:
        if not assessable or strong:
            return PillarVerdict("Pass", "I net institutional accumulation with meaningful strength (no group distributing)", drivers)
        return PillarVerdict("Weak", "I net institutional accumulation but size light", drivers)
    if _triggered(rule_results, "R-3") or (f_sum < 0 and t_sum < 0):
        return PillarVerdict("Fail", "I institutional flows net-negative", drivers)
    if foreign_positive or trust_positive:
        return PillarVerdict("Weak", "I mixed institutional flows (one group distributing)", drivers)
    return PillarVerdict("Weak", "I institutional flows flat/mixed", drivers)


def screen_M(market: MarketFeatures, params: Params, *, market_regime: str | None = None) -> PillarVerdict:
    # Deliberate choice: regime uses TAIEX/TPEX 150d(30w) trend + breadth, NOT O'Neil's
    # distribution-day / follow-through-day count. distribution_day_count exists on
    # MarketFeatures but stays informational — prior measurement found dist-day wiring
    # not justified for this dataset (see canslim_diagnostic). Keep trend/breadth regime.
    severity = market_regime if market_regime != "unknown" else None
    if severity is None:
        severity = regime_severity(market, params)
    warnings = list(market.data_warnings)
    if severity is None:
        return PillarVerdict("Insufficient_Data", "M market regime inputs unavailable", [], warnings)
    if severity == "risk_on":
        return PillarVerdict("Pass", "M market regime risk_on", ["regime_severity=risk_on"], warnings)
    if severity == "risk_off":
        return PillarVerdict("Weak", "M market regime risk_off", ["regime_severity=risk_off"], warnings)
    return PillarVerdict("Fail", "M market regime severe", ["regime_severity=severe"], warnings)


def _insufficient(pillar: str, reason: str, drivers: list[str], warnings: list[str] | None = None) -> PillarVerdict:
    return PillarVerdict("Insufficient_Data", f"{pillar} {reason}", drivers, warnings or [reason])


def _drivers(rule_results: RuleMap, *rule_ids: str) -> list[str]:
    out: list[str] = []
    for rule_id in rule_ids:
        result = rule_results.get(rule_id)
        if result is None:
            out.append(f"{rule_id}: unavailable")
        elif result.triggered:
            out.append(f"{rule_id}: triggered")
        elif result.data_warning:
            out.append(f"{rule_id}: {result.data_warning}")
        else:
            out.append(f"{rule_id}: not_triggered")
    return out


def _margin_expanding(features: CanslimFeatures | None) -> bool:
    """True when the latest operating margin is above the trailing 4-quarter average."""
    if features is None or not features.op_margin_last4:
        return False
    series = [value for value in features.op_margin_last4 if value is not None]
    if len(series) < 2:
        return False
    return series[-1] > (sum(series) / len(series))


def _net_strength(series: list[float] | None, avg_volume_20: float | None) -> float | None:
    """Cumulative institutional net buy over the window / 20d avg volume. None when
    inputs are missing (strength then not assessed)."""
    if not series or not avg_volume_20:
        return None
    return sum(series) / float(avg_volume_20)


def _fmt(value: float | None) -> str:
    return f"{value:.2f}" if value is not None else "n/a"


def _overheated(features: CanslimFeatures | None, cfg: Params) -> tuple[bool, str | None]:
    """True when a single-day volume spike is extreme AND the price is already pinned
    near (or above) its 52-week high — a likely climax/speculative surge rather than a
    healthy breakout. Missing volume data -> not flagged."""
    if features is None or features.latest_volume is None or not features.avg_volume_20:
        return False, None
    spike = float(features.latest_volume) / float(features.avg_volume_20)
    mult = float(cfg.get("overheat_volume_spike_mult", 4.0))
    ext_min = float(cfg.get("overheat_extension_min", -0.03))
    extended = features.pct_from_52w_high is not None and float(features.pct_from_52w_high) >= ext_min
    if spike >= mult and extended:
        return True, f"latest volume {spike:.1f}x 20d-avg while within {abs(ext_min) * 100:.0f}% of 52-week high"
    return False, None


def _earnings_acceleration(features: CanslimFeatures | None, cfg: Params) -> tuple[bool | None, bool]:
    """(accelerating, severe_deceleration) from the quarterly EPS YoY series.

    accelerating: True if latest YoY > prior quarter's YoY, False if lower, None if
    indeterminate (too few quarters). severe_deceleration: latest YoY fell below
    `accel_decel_ratio_floor` of the prior quarter's YoY (growth rate roughly halved)
    while the prior YoY was positive — O'Neil's deceleration warning."""
    if features is None or not features.quarterly_eps_yoy_series:
        return None, False
    series = [v for v in features.quarterly_eps_yoy_series if v is not None]
    min_q = int(cfg.get("accel_min_quarters", 3))
    if len(series) < 2:
        return None, False
    latest, prior = series[-1], series[-2]
    accelerating = latest > prior
    severe = False
    if len(series) >= min_q and prior > 0:
        floor = float(cfg.get("accel_decel_ratio_floor", 0.5))
        severe = latest < prior * floor
    return accelerating, severe


def _revenue_sustained(features: CanslimFeatures | None, cfg: Params) -> bool:
    """True when monthly revenue YoY has been positive in at least the configured
    fraction of recent months — i.e. growth is sustained, not a one-month blip."""
    if features is None or not features.month_revenue_yoy:
        return False
    lookback = int(cfg.get("revenue_sustained_lookback_months", 5))
    fraction = float(cfg.get("revenue_sustained_min_positive_fraction", 0.6))
    series = [value for value in features.month_revenue_yoy if value is not None][-lookback:]
    if not series:
        return False
    positive = sum(1 for value in series if value > 0)
    return (positive / len(series)) >= fraction


def _annual_eps_unstable(features: CanslimFeatures | None, cfg: Params) -> tuple[bool, str | None]:
    """True when a year-over-year annual-EPS step fell below the stability floor —
    a mid-period collapse that the endpoint 3y CAGR would otherwise hide."""
    if features is None or not features.annual_eps_last3 or len(features.annual_eps_last3) < 2:
        return False, None
    floor = float(cfg.get("annual_eps_stability_decline_floor", -1.0))
    series = features.annual_eps_last3
    for i in range(1, len(series)):
        prev, cur = series[i - 1], series[i]
        if prev is None or cur is None or prev <= 0:
            continue
        step = cur / prev - 1.0
        if step < floor:
            return True, f"annual EPS step {prev:.2f}->{cur:.2f} ({step:.2%}) below stability floor"
    return False, None


def _latest_revenue_yoy(features: CanslimFeatures | None) -> float | None:
    if features is None or not features.month_revenue_yoy:
        return None
    for value in reversed(features.month_revenue_yoy):
        if value is not None:
            return float(value)
    return None


def _triggered(rule_results: RuleMap, rule_id: str) -> bool:
    result = rule_results.get(rule_id)
    return bool(result and result.triggered)


def _has_warning(rule_results: RuleMap, rule_id: str) -> bool:
    result = rule_results.get(rule_id)
    return bool(result and result.data_warning)


def _warning_text(rule_results: RuleMap, rule_id: str) -> str:
    result = rule_results.get(rule_id)
    return str(result.data_warning) if result and result.data_warning else ""


def _stage2(features: CanslimFeatures) -> bool:
    values = (features.close, features.ma20, features.ma60, features.ma120, features.ma120_slope)
    if any(value is None for value in values):
        return False
    close, ma20, ma60, ma120, slope = values
    return bool(close > ma20 > ma60 > ma120 and slope >= 0)


def _positive_days(values: list[float]) -> int:
    return sum(1 for value in values if value > 0)
