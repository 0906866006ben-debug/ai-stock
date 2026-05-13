"""Minimal scorecard-based price-state classifier."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..contracts.enums import Horizon, TechnicalState
from ..contracts.feature_contract import FeatureBundle
from ..contracts.input_contract import ContextBundle
from ..registry.rule_registry import RuleRegistry
from ..traceability.trace import ReasonTrace


@dataclass
class StateEvidence:
    state: TechnicalState
    score: Decimal
    categories_fired: set[str]
    reasons: list[ReasonTrace]


class PriceStateClassifier:
    """Small but usable classifier aligned with the v1 states used by F-J."""

    def __init__(self, rule_registry: RuleRegistry | None = None, horizon: Horizon = Horizon.SHORT_TERM):
        self.registry = RuleRegistry.load_default() if rule_registry is None else rule_registry
        self.horizon = horizon
        self.thresholds = self.registry.thresholds_for(horizon)
        self.state_rules = self.registry.section("state_thresholds")

    def classify(self, features: FeatureBundle, context: ContextBundle) -> tuple[TechnicalState, list[ReasonTrace], set[str]]:
        evidences = [
            self._evaluate_strong_uptrend(features),
            self._evaluate_steady_uptrend(features),
            self._evaluate_tight_consolidation(features),
            self._evaluate_early_strengthening(features),
            self._evaluate_overheated(features),
            self._evaluate_early_weakening(features),
            self._evaluate_weak_rebound(features),
            self._evaluate_downtrend(features),
        ]
        valid = [e for e in evidences if len(e.categories_fired) >= 3]
        if not valid:
            return TechnicalState.MIXED_SIGNALS, self._mixed_reasons(evidences), set()
        winner = max(valid, key=lambda evidence: evidence.score)
        return winner.state, winner.reasons, winner.categories_fired

    def _evaluate_strong_uptrend(self, features: FeatureBundle) -> StateEvidence:
        ma20 = features.ma_values.get("ma20")
        ma60 = features.ma_values.get("ma60")
        slope20 = features.ma_slopes_pct.get("ma20")
        slope60 = features.ma_slopes_pct.get("ma60")
        rsi = features.latest_value("rsi")
        current = features.latest_close()
        rules = self.state_rules["strong_uptrend"]
        categories: set[str] = set()
        reasons: list[ReasonTrace] = []
        if ma20 and ma60 and current > ma20 and current > ma60:
            categories.add("price_position")
            reasons.append(_trace(features, "close", "收盤站上 MA20 與 MA60", "close > MA20 and close > MA60", current))
        if slope20 is not None and slope60 is not None and slope20 > Decimal(str(rules["min_ma20_slope_pct"])) and slope60 > Decimal(str(rules["min_ma60_slope_pct"])):
            categories.add("ma_geometry")
            reasons.append(_trace(features, "ma20_slope_pct", "MA20/MA60 斜率同步走升", "ma20_slope_pct > threshold", slope20))
        if features.volume_ratio_20d is not None and features.volume_ratio_20d > Decimal("1.1"):
            categories.add("volume_quality")
            reasons.append(_trace(features, "volume_ratio_20d", "量能高於 20 日均值", "volume_ratio_20d > 1.1", features.volume_ratio_20d))
        if features.swing_structure and len(features.swing_structure.swing_highs) >= 2 and len(features.swing_structure.swing_lows) >= 2:
            highs = features.swing_structure.last_two_highs
            lows = features.swing_structure.last_two_lows
            if highs[1].price > highs[0].price and lows[1].price > lows[0].price:
                categories.add("structure")
                reasons.append(_trace(features, "swing_structure", "高低點同步墊高", "HH and HL", highs[1].price))
        if rsi is not None and Decimal(str(rules["rsi_min"])) <= rsi <= Decimal(str(rules["rsi_max"])):
            categories.add("momentum")
            reasons.append(_trace(features, "rsi", "RSI 落在健康多頭區", "rsi between thresholds", rsi))
        score = Decimal(len(categories)) / Decimal("5")
        return StateEvidence(TechnicalState.STRONG_UPTREND, score, categories, reasons)

    def _evaluate_steady_uptrend(self, features: FeatureBundle) -> StateEvidence:
        ma20 = features.ma_values.get("ma20")
        ma60 = features.ma_values.get("ma60")
        slope20 = features.ma_slopes_pct.get("ma20")
        current = features.latest_close()
        rules = self.state_rules["steady_uptrend"]
        categories: set[str] = set()
        reasons: list[ReasonTrace] = []
        if ma20 and ma60 and current > ma20 and ma20 > ma60:
            categories.add("price_position")
            reasons.append(_trace(features, "ma20", "收盤與均線排列偏多", "close > ma20 > ma60", ma20))
        if slope20 is not None and Decimal(str(rules["min_ma20_slope_pct"])) <= slope20 <= Decimal(str(rules["max_ma20_slope_pct"])):
            categories.add("ma_geometry")
            reasons.append(_trace(features, "ma20_slope_pct", "MA20 斜率溫和走升", "slope within steady band", slope20))
        if features.volume_ratio_20d is not None and features.volume_ratio_20d <= Decimal("1.5"):
            categories.add("volume_quality")
            reasons.append(_trace(features, "volume_ratio_20d", "量能沒有失控放大", "volume_ratio_20d <= 1.5", features.volume_ratio_20d))
        if features.atr_ratio_percentile_60d is not None and Decimal("0.2") <= features.atr_ratio_percentile_60d <= Decimal("0.8"):
            categories.add("volatility")
            reasons.append(_trace(features, "atr_ratio_percentile_60d", "波動率位於中性區", "atr percentile in middle band", features.atr_ratio_percentile_60d))
        score = Decimal(len(categories)) / Decimal("4")
        return StateEvidence(TechnicalState.STEADY_UPTREND, score, categories, reasons)

    def _evaluate_tight_consolidation(self, features: FeatureBundle) -> StateEvidence:
        slope20 = features.ma_slopes_pct.get("ma20")
        slope60 = features.ma_slopes_pct.get("ma60")
        rules = self.state_rules["tight_consolidation"]
        categories: set[str] = set()
        reasons: list[ReasonTrace] = []
        if features.close_crosses_ma20_20d >= 3:
            categories.add("price_position")
            reasons.append(_trace(features, "close_crosses_ma20_20d", "近期反覆穿越 MA20", "cross count >= 3", Decimal(features.close_crosses_ma20_20d)))
        if slope20 is not None and slope60 is not None and abs(slope20) <= Decimal(str(rules["ma20_slope_abs_max_pct"])) and abs(slope60) <= Decimal(str(rules["ma60_slope_abs_max_pct"])):
            categories.add("ma_geometry")
            reasons.append(_trace(features, "ma_slopes_pct", "均線斜率接近平坦", "abs slopes within thresholds", slope20))
        if features.volume_ratio_20d is not None and features.volume_ratio_20d < Decimal(str(rules["volume_ratio_majority_max"])):
            categories.add("volume_quality")
            reasons.append(_trace(features, "volume_ratio_20d", "量能偏縮", "volume_ratio_20d < 1.0", features.volume_ratio_20d))
        if features.atr_ratio_percentile_60d is not None and features.atr_ratio_percentile_60d <= Decimal("0.4"):
            categories.add("volatility")
            reasons.append(_trace(features, "atr_ratio_percentile_60d", "波動率壓縮", "atr percentile <= 0.4", features.atr_ratio_percentile_60d))
        score = Decimal(len(categories)) / Decimal("4")
        return StateEvidence(TechnicalState.TIGHT_CONSOLIDATION, score, categories, reasons)

    def _evaluate_early_strengthening(self, features: FeatureBundle) -> StateEvidence:
        slope20 = features.ma_slopes_pct.get("ma20")
        slope60 = features.ma_slopes_pct.get("ma60")
        rsi = features.latest_value("rsi")
        categories: set[str] = set()
        reasons: list[ReasonTrace] = []
        ma20 = features.ma_values.get("ma20")
        close = features.latest_close()
        if ma20 is not None and close > ma20:
            categories.add("price_position")
            reasons.append(_trace(features, "close", "收盤重新站回 MA20", "close > ma20", close))
        if slope20 is not None and slope20 >= Decimal(str(self.state_rules["early_strengthening"]["ma20_transition_floor_pct"])):
            categories.add("ma_geometry")
            reasons.append(_trace(features, "ma20_slope_pct", "MA20 斜率從負轉平", "ma20_slope_pct >= floor", slope20))
        if features.volume_ratio_20d is not None and features.volume_ratio_20d >= Decimal(str(self.state_rules["early_strengthening"]["reclaim_volume_ratio_min"])):
            categories.add("volume_quality")
            reasons.append(_trace(features, "volume_ratio_20d", "站回均線伴隨量能", "volume_ratio_20d >= 1.1", features.volume_ratio_20d))
        if rsi is not None and rsi >= Decimal("50"):
            categories.add("momentum")
            reasons.append(_trace(features, "rsi", "RSI 站回 50 軸上方", "rsi >= 50", rsi))
        if slope60 is not None and slope60 < Decimal(str(self.state_rules["early_strengthening"]["ma60_slope_guardrail_min_pct"])):
            return StateEvidence(TechnicalState.EARLY_STRENGTHENING, Decimal("0"), set(), [])
        score = Decimal(len(categories)) / Decimal("4")
        return StateEvidence(TechnicalState.EARLY_STRENGTHENING, score, categories, reasons)

    def _evaluate_overheated(self, features: FeatureBundle) -> StateEvidence:
        current = features.latest_close()
        ma20 = features.ma_values.get("ma20")
        rsi = features.latest_value("rsi")
        categories: set[str] = set()
        reasons: list[ReasonTrace] = []
        if ma20 is not None and current > ma20:
            categories.add("price_position")
            reasons.append(_trace(features, "close", "收盤仍位於 MA20 之上", "close > ma20", current))
        if features.deviation_from_ma20_pct is not None and features.deviation_from_ma20_pct > Decimal(str(self.thresholds["overextension_deviation_threshold_pct"])):
            categories.add("ma_geometry")
            reasons.append(_trace(features, "deviation_from_ma20_pct", "乖離過大", "deviation_from_ma20_pct > threshold", features.deviation_from_ma20_pct))
        if rsi is not None and rsi >= Decimal(str(self.state_rules["overheated_high_level"]["rsi_min"])):
            categories.add("momentum")
            reasons.append(_trace(features, "rsi", "RSI 進入過熱區", "rsi >= threshold", rsi))
        if features.atr_ratio_percentile_60d is not None and features.atr_ratio_percentile_60d >= Decimal("0.75"):
            categories.add("volatility")
            reasons.append(_trace(features, "atr_ratio_percentile_60d", "波動率擴張", "atr percentile >= 0.75", features.atr_ratio_percentile_60d))
        score = Decimal(len(categories)) / Decimal("4")
        return StateEvidence(TechnicalState.OVERHEATED_HIGH_LEVEL, score, categories, reasons)

    def _evaluate_early_weakening(self, features: FeatureBundle) -> StateEvidence:
        ma20 = features.ma_values.get("ma20")
        slope20 = features.ma_slopes_pct.get("ma20")
        close = features.latest_close()
        rsi = features.latest_value("rsi")
        categories: set[str] = set()
        reasons: list[ReasonTrace] = []
        if ma20 is not None and close < ma20:
            categories.add("price_position")
            reasons.append(_trace(features, "close", "收盤跌破 MA20", "close < ma20", close))
        if slope20 is not None and slope20 <= Decimal("0"):
            categories.add("ma_geometry")
            reasons.append(_trace(features, "ma20_slope_pct", "MA20 斜率轉弱", "ma20_slope_pct <= 0", slope20))
        if features.volume_ratio_20d is not None and features.volume_ratio_20d >= Decimal(str(self.state_rules["early_weakening"]["breakdown_volume_ratio_min"])):
            categories.add("volume_quality")
            reasons.append(_trace(features, "volume_ratio_20d", "跌破伴隨量增", "volume_ratio_20d >= 1.2", features.volume_ratio_20d))
        if rsi is not None and rsi < Decimal("50"):
            categories.add("momentum")
            reasons.append(_trace(features, "rsi", "RSI 掉回 50 軸下方", "rsi < 50", rsi))
        score = Decimal(len(categories)) / Decimal("4")
        return StateEvidence(TechnicalState.EARLY_WEAKENING, score, categories, reasons)

    def _evaluate_weak_rebound(self, features: FeatureBundle) -> StateEvidence:
        ma60 = features.ma_values.get("ma60")
        slope60 = features.ma_slopes_pct.get("ma60")
        rsi = features.latest_value("rsi")
        categories: set[str] = set()
        reasons: list[ReasonTrace] = []
        close = features.latest_close()
        if ma60 is not None and close < ma60:
            categories.add("price_position")
            reasons.append(_trace(features, "close", "反彈仍未站回 MA60", "close < ma60", close))
        if slope60 is not None and slope60 <= Decimal("0"):
            categories.add("ma_geometry")
            reasons.append(_trace(features, "ma60_slope_pct", "MA60 仍未翻揚", "ma60_slope_pct <= 0", slope60))
        if features.volume_ratio_20d is not None and features.volume_ratio_20d < Decimal("1.0"):
            categories.add("volume_quality")
            reasons.append(_trace(features, "volume_ratio_20d", "反彈量能不足", "volume_ratio_20d < 1.0", features.volume_ratio_20d))
        if rsi is not None and rsi < Decimal(str(self.state_rules["weak_rebound"]["rsi_reclaim_fail_max"])):
            categories.add("momentum")
            reasons.append(_trace(features, "rsi", "RSI 反彈未站穩強勢區", "rsi < 55", rsi))
        score = Decimal(len(categories)) / Decimal("4")
        return StateEvidence(TechnicalState.WEAK_REBOUND, score, categories, reasons)

    def _evaluate_downtrend(self, features: FeatureBundle) -> StateEvidence:
        ma20 = features.ma_values.get("ma20")
        ma60 = features.ma_values.get("ma60")
        slope20 = features.ma_slopes_pct.get("ma20")
        slope60 = features.ma_slopes_pct.get("ma60")
        close = features.latest_close()
        categories: set[str] = set()
        reasons: list[ReasonTrace] = []
        if ma20 is not None and ma60 is not None and close < ma20 and close < ma60:
            categories.add("price_position")
            reasons.append(_trace(features, "close", "收盤位於 MA20 與 MA60 之下", "close < ma20 and ma60", close))
        if slope20 is not None and slope60 is not None and slope20 <= Decimal(str(self.state_rules["downtrend_continuation"]["max_ma20_slope_pct"])) and slope60 <= Decimal(str(self.state_rules["downtrend_continuation"]["max_ma60_slope_pct"])):
            categories.add("ma_geometry")
            reasons.append(_trace(features, "ma_slopes_pct", "均線斜率同步下彎", "ma20/ma60 slopes below thresholds", slope20))
        if features.volume_median_down_days_5 is not None and features.volume_median_up_days_5 is not None and features.volume_median_down_days_5 > features.volume_median_up_days_5:
            categories.add("volume_quality")
            reasons.append(_trace(features, "volume_median_down_days_5", "下跌日量能主導", "down-day volume median > up-day volume median", features.volume_median_down_days_5))
        if features.swing_structure and len(features.swing_structure.swing_highs) >= 2 and len(features.swing_structure.swing_lows) >= 2:
            highs = features.swing_structure.last_two_highs
            lows = features.swing_structure.last_two_lows
            if highs[1].price < highs[0].price and lows[1].price < lows[0].price:
                categories.add("structure")
                reasons.append(_trace(features, "swing_structure", "高低點同步下移", "LH and LL", lows[1].price))
        score = Decimal(len(categories)) / Decimal("4")
        return StateEvidence(TechnicalState.DOWNTREND_CONTINUATION, score, categories, reasons)

    def _mixed_reasons(self, evidences: list[StateEvidence]) -> list[ReasonTrace]:
        return [reason for evidence in evidences for reason in evidence.reasons[:1]][:4]


def _trace(features: FeatureBundle, source_field: str, reason_text: str, calculation: str, value: Decimal) -> ReasonTrace:
    return ReasonTrace(
        reason_text=reason_text,
        source_field=source_field,
        timestamp=features.series.latest().date,
        calculation=calculation,
        calculation_value=value,
    )
