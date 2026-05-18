from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.screeners.multi_factor_surge.chip_signals import score_chips
from backend.screeners.multi_factor_surge.classifier import classify_candidate
from backend.screeners.multi_factor_surge.config import CONFIG, RULE_SET_VERSION
from backend.screeners.multi_factor_surge.feature_builder import (
    FundamentalsProvider,
    build_stock_context,
    load_universe,
)
from backend.screeners.multi_factor_surge.fundamental_signals import score_fundamentals
from backend.screeners.multi_factor_surge.funnel import FunnelBuilder
from backend.screeners.multi_factor_surge.liquidity_signals import score_liquidity
from backend.screeners.multi_factor_surge.risk_signals import score_risk
from backend.screeners.multi_factor_surge.schemas import MultiFactorResponse, MultiFactorResult
from backend.screeners.multi_factor_surge.scoring import composite_scores
from backend.screeners.multi_factor_surge.sustain_signals import score_sustain
from backend.screeners.multi_factor_surge.technical_signals import score_technicals


logger = logging.getLogger(__name__)
TW_TIMEZONE = timezone(timedelta(hours=8))


@dataclass(frozen=True)
class MultiFactorParameters:
    limit: int = 50
    market: str = "all"
    candidate_type: str | None = None
    min_surge_score: int = 0
    include_unfit: bool = False
    debug: bool = False
    scan_limit: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "limit": self.limit,
            "market": self.market,
            "candidate_type": self.candidate_type,
            "min_surge_score": self.min_surge_score,
            "include_unfit": self.include_unfit,
            "debug": self.debug,
            "scan_limit": self.scan_limit,
        }


class UniverseLoadError(RuntimeError):
    pass


async def scan_multi_factor_surge(
    parameters: MultiFactorParameters,
    *,
    universe: list[dict[str, Any]] | None = None,
    fundamentals_provider: FundamentalsProvider | None = None,
) -> MultiFactorResponse:
    if parameters.market not in CONFIG["universe"]["allowed_markets"]:
        raise ValueError("market must be all, twse, or tpex")

    data_warnings: list[str] = []
    if universe is None:
        universe, universe_stats, warnings = await load_universe(parameters.market, parameters.scan_limit)
        data_warnings.extend(warnings)
    else:
        universe_stats = {
            "raw_universe_size": len(universe),
            "common_stock_filter_count": len(universe),
            "excluded_by_pattern_count": {"etf": 0, "warrant": 0, "preferred": 0, "ky": 0, "name_keyword": 0, "industry": 0, "market": 0},
        }

    if not universe:
        raise UniverseLoadError("Multi-factor surge universe is empty.")

    funnel = FunnelBuilder()
    funnel.initialize_universe(
        int(universe_stats["raw_universe_size"]),
        int(universe_stats["common_stock_filter_count"]),
        dict(universe_stats["excluded_by_pattern_count"]),
    )

    rows: list[MultiFactorResult] = []
    for item in universe:
        stock_id = str(item.get("stock_code") or item.get("code") or "").strip()
        stock_name = str(item.get("company_name") or item.get("name") or stock_id)
        try:
            context = await build_stock_context(item, fundamentals_provider=fundamentals_provider)
            bars = len(context.ohlcv)
            if bars < int(CONFIG["history"]["minimum_bars"]):
                funnel.add_failed("ohlcv_sufficient", {"stock_id": stock_id, "stock_name": stock_name, "bars_available": bars})
                continue
            funnel.stages["ohlcv_sufficient_count"] += 1

            fundamental, fundamental_metrics = score_fundamentals(context.fundamentals)
            chip, chip_metrics = score_chips(context.stock_id)
            technical, technical_metrics = score_technicals(context.ohlcv)
            sustain, sustain_metrics = score_sustain(context.ohlcv)
            risk, risk_metrics = score_risk(context.ohlcv, technical_metrics)
            liquidity, liquidity_metrics = score_liquidity(context.ohlcv)

            missing_data = _dedupe(
                context.missing_data
                + fundamental.missing_data
                + chip.missing_data
                + technical.missing_data
                + sustain.missing_data
                + risk.missing_data
                + liquidity.missing_data
            )
            data_quality_flags = _dedupe(
                context.data_quality_flags
                + fundamental.data_quality_flags
                + chip.data_quality_flags
                + technical.data_quality_flags
                + sustain.data_quality_flags
                + risk.data_quality_flags
                + liquidity.data_quality_flags
            )
            risk_flags = _dedupe(risk.risk_flags + fundamental.risk_flags + chip.risk_flags + technical.risk_flags + sustain.risk_flags + liquidity.risk_flags)

            scores, risk_score, confidence_score, surge_score = composite_scores(
                fundamental,
                chip,
                technical,
                sustain,
                liquidity,
                risk,
                missing_data,
                data_quality_flags,
            )
            candidate_type = classify_candidate(
                surge_score=surge_score,
                risk_score=risk_score,
                fundamental=fundamental,
                chip=chip,
                technical=technical,
                sustain=sustain,
                liquidity_score=liquidity.score,
                risk_flags=risk_flags,
            )
            if not liquidity_metrics["liquidity_pass"]:
                candidate_type = "不符合"
            if surge_score < parameters.min_surge_score:
                candidate_type = "不符合"
            if parameters.candidate_type and candidate_type != parameters.candidate_type:
                _update_funnel(funnel, fundamental, chip, technical, sustain, liquidity, risk_score, risk_flags)
                continue

            metrics = {
                **fundamental_metrics,
                **chip_metrics,
                **technical_metrics,
                **sustain_metrics,
                **risk_metrics,
                **liquidity_metrics,
            }
            result = MultiFactorResult(
                stock_id=context.stock_id,
                stock_name=context.stock_name,
                candidate_type=candidate_type,
                surge_score=surge_score,
                confidence_score=confidence_score,
                risk_score=risk_score,
                scores=scores,
                metrics=metrics,
                reasons=_dedupe(fundamental.reasons + chip.reasons + technical.reasons + sustain.reasons + liquidity.reasons),
                watch_conditions=_watch_conditions(metrics),
                invalidation=_invalidation(metrics),
                risk_flags=risk_flags,
                missing_data=missing_data,
                data_quality_flags=data_quality_flags,
            )
            _update_funnel(funnel, fundamental, chip, technical, sustain, liquidity, risk_score, risk_flags, result=result)
            if parameters.include_unfit or candidate_type != "不符合":
                rows.append(result)
        except Exception as exc:
            logger.warning("multi-factor screener skipped %s: %s", stock_id, exc)
            funnel.stages["error_count"] += 1
            continue

    rows.sort(key=lambda item: item.surge_score, reverse=True)
    matched_count = sum(1 for item in rows if item.candidate_type != "不符合")
    rows = rows[: parameters.limit]
    for rank, row in enumerate(rows, start=1):
        row.rank = rank
    funnel.stages["final_matched_count"] = matched_count
    return MultiFactorResponse(
        generated_at=datetime.now(TW_TIMEZONE).isoformat(),
        rule_set_version=RULE_SET_VERSION,
        is_v1_hypothesis=bool(CONFIG["is_v1_hypothesis"]),
        backtest_required=bool(CONFIG["backtest_required"]),
        universe_size=len(universe),
        matched_count=matched_count,
        parameters=parameters.to_dict(),
        data_warnings=_dedupe(data_warnings),
        funnel_report=funnel.build() if parameters.debug else None,
        results=rows,
    )


def _update_funnel(
    funnel: FunnelBuilder,
    fundamental: Any,
    chip: Any,
    technical: Any,
    sustain: Any,
    liquidity: Any,
    risk_score: int,
    risk_flags: list[str],
    *,
    result: MultiFactorResult | None = None,
) -> None:
    stock = {"stock_id": result.stock_id, "stock_name": result.stock_name} if result else {}
    if liquidity.score >= 60 and result and result.metrics.get("liquidity_pass"):
        funnel.stages["liquidity_pass_count"] += 1
    elif result:
        funnel.add_failed("liquidity_avg_volume_5d>=500000_shares", {**stock, "avg_volume_5d_shares": result.metrics.get("avg_volume_5d_shares")})

    if not fundamental.is_neutral_fallback:
        funnel.stages["fundamental_data_available_count"] += 1
    if not fundamental.is_neutral_fallback and fundamental.score >= int(CONFIG["fundamental"]["high_score"]):
        funnel.stages["fundamental_score_high_count"] += 1
    elif result:
        funnel.add_failed("fundamental_score_high", {**stock, "fundamental_score": fundamental.score, "missing_data": fundamental.missing_data})

    if not chip.is_neutral_fallback:
        funnel.stages["chip_data_available_count"] += 1
    if not chip.is_neutral_fallback and chip.score >= int(CONFIG["chip"]["high_score"]):
        funnel.stages["chip_score_high_count"] += 1
    elif result:
        funnel.add_failed("chip_score_high", {**stock, "chip_score": chip.score, "missing_data": chip.missing_data})

    if technical.score >= int(CONFIG["technical"]["high_score"]):
        funnel.stages["technical_score_high_count"] += 1
    elif result:
        funnel.add_failed("technical_score_high", {**stock, "technical_score": technical.score})

    if sustain.score >= int(CONFIG["sustain"]["high_score"]):
        funnel.stages["sustain_score_high_count"] += 1
    elif result:
        funnel.add_failed("sustain_score_high", {**stock, "breakout_sustain_score": sustain.score})

    if risk_score < int(CONFIG["risk"]["overheat_score"]) and not any(flag in risk_flags for flag in ("long_upper_shadow_on_high_volume", "gap_up_exhaustion", "recent_overheat")):
        funnel.stages["risk_filter_pass_count"] += 1
    elif result:
        funnel.add_failed("risk_filter", {**stock, "risk_score": risk_score, "risk_flags": risk_flags})


def _watch_conditions(metrics: dict[str, Any]) -> list[str]:
    return [
        "持續站穩 20MA",
        "OBV 維持於 10MA 之上",
        f"量能維持高於 5 日均量 {metrics.get('avg_volume_5d_lots', 0):,.0f} 張附近",
    ]


def _invalidation(metrics: dict[str, Any]) -> list[str]:
    return [
        "跌破 20MA",
        "跌破前波爆量紅K低點",
        "爆量長上影且隔日無法收復",
    ]


def _dedupe(items: list[Any]) -> list[Any]:
    seen = set()
    result = []
    for item in items:
        marker = repr(item)
        if marker in seen:
            continue
        seen.add(marker)
        result.append(item)
    return result
