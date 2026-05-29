from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

import pandas as pd

from backend.app.models.screener_schemas import (
    CandidateMetrics,
    CandidateScores,
    ScreenerResponse,
    SurgeCandidateResult,
)
from backend.app.services.data_sources import settings as data_source_settings
from backend.app.services.data_sources.source_models import SourceInfo
from backend.app.services.data_sources.tpex_client import fetch_tpex_mainboard_quote_map
from backend.app.services.finmind_market import get_finmind_rate_limit_state, get_tw_price_history_with_source
from backend.app.services.screener_rules import load_surge_candidate_rules, require_rule
from backend.app.services.sector_service import get_sector_info, is_ai_tech_stock, list_ai_tech_codes
from backend.app.services.tw_stocks_list import get_tw_stocks
from backend.app.services.strategy.canslim.observer import observe as observe_canslim
from backend.app.services.strategy.canslim.types import MarketFeatures


logger = logging.getLogger(__name__)
TW_TIMEZONE = timezone(timedelta(hours=8))
ProgressCallback = Callable[[dict[str, Any]], bool | None]


class ScanCancelled(RuntimeError):
    pass


@dataclass(frozen=True)
class ScreenerParameters:
    min_return_60d: float
    max_return_60d: float
    max_base_return: float
    min_return_20d: float
    min_avg_volume_lots: int
    min_avg_turnover: int
    scan_limit: int
    limit: int
    market: str
    sort_by: str
    candidate_type: Optional[str]
    include_unfit: bool
    ai_tech_only: bool = False    # 預設 False 維持向下相容；API/UI 預設打開
    include_canslim: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "min_return_60d": self.min_return_60d,
            "max_return_60d": self.max_return_60d,
            "max_base_return": self.max_base_return,
            "min_return_20d": self.min_return_20d,
            "min_avg_volume_lots": self.min_avg_volume_lots,
            "min_avg_turnover": self.min_avg_turnover,
            "scan_limit": self.scan_limit,
            "limit": self.limit,
            "market": self.market,
            "sort_by": self.sort_by,
            "candidate_type": self.candidate_type,
            "include_unfit": self.include_unfit,
            "ai_tech_only": self.ai_tech_only,
            "include_canslim": self.include_canslim,
        }


class UniverseLoadError(RuntimeError):
    pass


def _report_progress(progress_callback: Optional[ProgressCallback], payload: dict[str, Any]) -> None:
    if progress_callback and progress_callback(payload) is False:
        raise ScanCancelled("Screener scan cancelled.")


def default_screener_parameters() -> ScreenerParameters:
    rules = load_surge_candidate_rules()
    return ScreenerParameters(
        min_return_60d=float(require_rule(rules, "price_position.min_return_60d")),
        max_return_60d=float(require_rule(rules, "price_position.max_return_60d")),
        max_base_return=float(require_rule(rules, "price_position.max_base_return_abs")),
        min_return_20d=float(require_rule(rules, "price_position.min_return_20d")),
        min_avg_volume_lots=int(require_rule(rules, "liquidity.min_avg_volume_20_lots")),
        min_avg_turnover=int(require_rule(rules, "liquidity.min_avg_turnover_20")),
        scan_limit=int(require_rule(rules, "api.default_scan_limit")),
        limit=int(require_rule(rules, "api.default_limit")),
        market=str(require_rule(rules, "api.default_market")),
        sort_by=str(require_rule(rules, "api.default_sort_by")),
        candidate_type=None,
        include_unfit=False,
        include_canslim=False,
    )


def _clamp_score(value: float) -> int:
    return max(0, min(100, int(round(value))))


def _safe_ratio(numerator: float, denominator: float, fallback: float = 0.0) -> float:
    return numerator / denominator if denominator else fallback


class _DataFrameStoreAdapter:
    def __init__(self, stock_id: str, df: pd.DataFrame) -> None:
        self.stock_id = str(stock_id)
        self.df = df.copy().reset_index(drop=True)

    def get_ohlcv_as_of(self, stock_id: str, as_of_date: str, lookback_bars: int) -> pd.DataFrame:
        if str(stock_id) != self.stock_id or self.df.empty:
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume", "turnover"])
        frame = self.df.copy()
        if "date" not in frame:
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume", "turnover"])
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        cutoff = pd.to_datetime(as_of_date)
        frame = frame[frame["date"].notna() & (frame["date"] <= cutoff)].tail(lookback_bars).copy()
        frame["date"] = frame["date"].dt.strftime("%Y-%m-%d")
        if "turnover" not in frame and "close" in frame and "volume" in frame:
            frame["turnover"] = pd.to_numeric(frame["close"], errors="coerce") * pd.to_numeric(frame["volume"], errors="coerce")
        return frame.reset_index(drop=True)


def _attach_canslim_observation(
    result: SurgeCandidateResult,
    stock_id: str,
    df: pd.DataFrame,
    as_of_date: str,
) -> None:
    try:
        cards = observe_canslim(
            stock_id,
            as_of_date,
            store=_DataFrameStoreAdapter(stock_id, df),
            market=MarketFeatures(),
            event_window_active=None,
        )
        swing = cards["swing_term"]
        result.metrics.canslim_grade = str(swing.scores.get("grade"))
        result.metrics.canslim_signal = int(swing.scores.get("signal", 0))
        result.metrics.canslim_risk = int(swing.scores.get("risk", 0))
        result.metrics.canslim_confidence = int(swing.scores.get("confidence", 0))
        result.metrics.canslim_hard_blocked = bool(swing.scores.get("hard_blocked", False))
        result.scores.canslim_signal = result.metrics.canslim_signal
        result.scores.canslim_risk = result.metrics.canslim_risk
        result.scores.canslim_confidence = result.metrics.canslim_confidence
        result.extras["canslim"] = {
            horizon: card.model_dump()
            for horizon, card in cards.items()
        }
        if result.candidate_type == "不符合" and result.metrics.canslim_signal and result.metrics.canslim_signal > 0:
            result.candidate_type = "CANSLIM觀察"
    except Exception as exc:
        result.extras["canslim_error"] = str(exc)


def _canonicalize_ohlcv(df: pd.DataFrame) -> tuple[pd.DataFrame, bool]:
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = df.columns.get_level_values(0)

    column_map: dict[str, str] = {}
    for col in df.columns:
        key = str(col).strip().lower()
        if key in {"open", "maxopen"}:
            column_map[col] = "open"
        elif key in {"high", "max"}:
            column_map[col] = "high"
        elif key in {"low", "min"}:
            column_map[col] = "low"
        elif key == "close":
            column_map[col] = "close"
        elif key in {"volume", "trading_volume"}:
            column_map[col] = "volume"
        elif key in {"turnover", "turnover_value", "trading_money"}:
            column_map[col] = "turnover_value"

    normalized = df.rename(columns=column_map).copy()
    required = ["open", "high", "low", "close", "volume"]
    missing = [col for col in required if col not in normalized.columns]
    if missing:
        raise ValueError(f"Missing OHLCV columns: {', '.join(missing)}")

    for col in required + (["turnover_value"] if "turnover_value" in normalized.columns else []):
        normalized[col] = pd.to_numeric(normalized[col], errors="coerce")

    normalized = normalized.dropna(subset=required)
    has_turnover = "turnover_value" in normalized.columns and not normalized["turnover_value"].isna().all()
    if has_turnover:
        normalized["turnover_value"] = normalized["turnover_value"].fillna(
            normalized["close"] * normalized["volume"]
        )
    return normalized, has_turnover


def candles_to_dataframe(candles: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "date": item.get("time") or item.get("date") or item.get("Date"),
            "open": item.get("open") or item.get("Open"),
            "high": item.get("high") or item.get("High") or item.get("max"),
            "low": item.get("low") or item.get("Low") or item.get("min"),
            "close": item.get("close") or item.get("Close"),
            "volume": item.get("volume") or item.get("Volume") or item.get("Trading_Volume"),
            "turnover_value": item.get("turnover_value") or item.get("Turnover") or item.get("Trading_money"),
        }
        for item in candles
    ])


def _normalize_date_text(value: Any) -> str:
    try:
        parsed = pd.to_datetime(value)
        if pd.isna(parsed):
            return str(value or "")
        return parsed.date().isoformat()
    except Exception:
        return str(value or "")


def _apply_official_latest_quote(
    candles: list[dict[str, Any]],
    official_quote: Optional[dict[str, Any]],
    source_info: SourceInfo,
) -> tuple[list[dict[str, Any]], SourceInfo, bool]:
    if not official_quote or not candles:
        return candles, source_info, False

    official_date = _normalize_date_text(official_quote.get("date"))
    if not official_date:
        return candles, source_info, False

    patched = [dict(item) for item in candles]
    latest_date = _normalize_date_text(patched[-1].get("time") or patched[-1].get("date") or patched[-1].get("Date"))

    official_candle = {
        "time": official_date,
        "open": official_quote.get("open"),
        "high": official_quote.get("high"),
        "low": official_quote.get("low"),
        "close": official_quote.get("close"),
        "volume": official_quote.get("volume"),
        "turnover_value": official_quote.get("turnover_value"),
    }
    if any(official_candle.get(key) is None for key in ("open", "high", "low", "close", "volume")):
        return candles, source_info, False

    if latest_date == official_date:
        patched[-1].update(official_candle)
    elif latest_date < official_date:
        patched.append(official_candle)
    else:
        return candles, source_info, False

    warnings = list(source_info.data_warnings)
    if "tpex_official_latest" not in warnings:
        warnings.append("tpex_official_latest")
    updated_source_info = SourceInfo(
        ohlcv_source=source_info.ohlcv_source,
        turnover_source="official" if official_quote.get("turnover_value") is not None else source_info.turnover_source,
        market_index_source=source_info.market_index_source,
        is_mock_data=source_info.is_mock_data,
        bars_count=len(patched),
        data_warnings=warnings,
    )
    return patched, updated_source_info, True


def _ema(close: pd.Series, period: int) -> pd.Series:
    values = [float(value) for value in close.tolist()]
    result = [float("nan")] * len(values)
    if len(values) < period:
        return pd.Series(result, index=close.index)

    seed = sum(values[:period]) / period
    result[period - 1] = seed
    alpha = 2 / (period + 1)
    for index in range(period, len(values)):
        result[index] = values[index] * alpha + result[index - 1] * (1 - alpha)
    return pd.Series(result, index=close.index)


def _score_liquidity(avg_turnover_20: float, avg_volume_20_lots: float, rules: dict[str, Any]) -> int:
    if (
        avg_turnover_20 >= float(require_rule(rules, "liquidity.tier_very_high_turnover"))
        and avg_volume_20_lots >= float(require_rule(rules, "liquidity.tier_very_high_volume_lots"))
    ):
        return 90
    if (
        avg_turnover_20 >= float(require_rule(rules, "liquidity.tier_high_turnover"))
        and avg_volume_20_lots >= float(require_rule(rules, "liquidity.tier_high_volume_lots"))
    ):
        return 75
    if (
        avg_turnover_20 >= float(require_rule(rules, "liquidity.tier_mid_turnover"))
        and avg_volume_20_lots >= float(require_rule(rules, "liquidity.tier_mid_volume_lots"))
    ):
        return 60
    if avg_turnover_20 >= float(require_rule(rules, "liquidity.tier_low_turnover")):
        return 40
    return 20


def _score_price_position(
    return_60d: float,
    return_20d: float,
    return_60_to_20: float,
    return_5d: float,
    rules: dict[str, Any],
) -> int:
    score = 15
    if float(require_rule(rules, "price_position.medium_return_60d_max")) <= return_60d <= float(require_rule(rules, "price_position.extended_return_60d_max")):
        score += 45
    elif float(require_rule(rules, "price_position.low_return_60d_max")) <= return_60d < float(require_rule(rules, "price_position.medium_return_60d_max")):
        score += 30
    elif float(require_rule(rules, "price_position.min_return_60d")) <= return_60d < float(require_rule(rules, "price_position.low_return_60d_max")):
        score += 15
    elif float(require_rule(rules, "price_position.extended_return_60d_max")) < return_60d <= float(require_rule(rules, "price_position.max_return_60d")):
        score += 25
    if return_20d >= float(require_rule(rules, "price_position.min_return_20d")):
        score += 20
    elif return_20d >= float(require_rule(rules, "price_position.medium_return_20d")):
        score += 10
    if abs(return_60_to_20) <= float(require_rule(rules, "price_position.max_base_return_abs")):
        score += 15
    elif abs(return_60_to_20) <= float(require_rule(rules, "price_position.medium_base_return_abs")):
        score += 8
    if return_5d >= float(require_rule(rules, "price_position.overheat_return_5d")):
        score -= 15
    elif return_5d >= float(require_rule(rules, "price_position.moderate_return_5d")):
        score -= 5
    return _clamp_score(score)


def _score_base(base_range_pct: float, volume_contraction_ratio: float, base_return: float, rules: dict[str, Any]) -> int:
    score = 0
    if abs(base_return) <= float(require_rule(rules, "price_position.max_base_return_abs")):
        score += 45
    elif abs(base_return) <= float(require_rule(rules, "price_position.medium_base_return_abs")):
        score += 28

    if base_range_pct < float(require_rule(rules, "base.high_score_range_pct")):
        score += 25
    elif base_range_pct < float(require_rule(rules, "base.max_range_pct")):
        score += 18
    elif base_range_pct < float(require_rule(rules, "base.loose_range_pct")):
        score += 10

    if volume_contraction_ratio < float(require_rule(rules, "base.contraction_ratio")):
        score += 30
    elif volume_contraction_ratio < float(require_rule(rules, "base.neutral_contraction_ratio")):
        score += 20
    elif volume_contraction_ratio < float(require_rule(rules, "base.expansion_ratio")):
        score += 12
    return _clamp_score(score)


def _score_volume(
    volume_recovery_ratio_5d: float,
    volume_today_ratio_20: float,
    volume_contraction_ratio: float,
    rules: dict[str, Any],
) -> int:
    score = 20
    if volume_recovery_ratio_5d > float(require_rule(rules, "volume.strong_recovery_ratio")) and volume_contraction_ratio < float(require_rule(rules, "base.contraction_ratio")):
        score += 55
    elif volume_recovery_ratio_5d > float(require_rule(rules, "volume.sustained_recovery_ratio")):
        score += 40
    elif volume_recovery_ratio_5d > float(require_rule(rules, "volume.mild_recovery_ratio")):
        score += 25
    elif volume_recovery_ratio_5d >= float(require_rule(rules, "volume.weak_recovery_ratio")):
        score += 15
    else:
        score += 5

    if volume_today_ratio_20 > float(require_rule(rules, "volume.single_day_surge_ratio")):
        score += 10
    if volume_contraction_ratio < float(require_rule(rules, "base.neutral_contraction_ratio")):
        score += 10
    return _clamp_score(score)


def _score_ema(
    ema_spread: float,
    close_today: float,
    ema5: float,
    ema10: float,
    ema20: float,
    ema5_slope: float,
    ema10_slope: float,
    ema20_slope: float,
    bullish_stack: bool,
    rules: dict[str, Any],
) -> int:
    score = 10
    if ema_spread < float(require_rule(rules, "ema.tight_spread")):
        score += 34
    elif ema_spread < float(require_rule(rules, "ema.medium_spread")):
        score += 26
    elif ema_spread < float(require_rule(rules, "ema.initial_move_spread")):
        score += 18
    elif ema_spread < float(require_rule(rules, "ema.extended_spread")):
        score += 8
    else:
        score += 0

    if close_today >= ema20:
        score += 8
    if close_today >= ema10:
        score += 8
    if close_today >= ema5:
        score += 8
    if ema5_slope > float(require_rule(rules, "ema.ema5_micro_upturn_min")):
        score += 18
    if ema10_slope > float(require_rule(rules, "ema.ema10_flat_floor")):
        score += 12
    if ema20_slope > float(require_rule(rules, "ema.ema20_flat_floor")):
        score += 10
    if ema5 > ema10:
        score += 8
    if ema10 > ema20:
        score += 8
    if bullish_stack:
        score += 4
    return _clamp_score(score)


def _score_setup_price_position(
    return_20d: float,
    return_60d: float,
    return_90d: float,
    close_to_base_high_ratio: float,
    close_from_base_low_pct: float,
    close_from_ema20_pct: float,
    rules: dict[str, Any],
) -> int:
    score = 0
    if return_20d <= float(require_rule(rules, "price_position.pre_breakout_return_20d_high")):
        score += 24
    elif return_20d <= float(require_rule(rules, "price_position.pre_breakout_return_20d_medium")):
        score += 16
    elif return_20d <= float(require_rule(rules, "price_position.max_return_20d_not_surged")):
        score += 6

    if return_60d <= float(require_rule(rules, "price_position.pre_breakout_return_60d_max")):
        score += 18
    elif return_60d <= float(require_rule(rules, "classification.momentum_return_60d_max")):
        score += 8

    if return_90d <= float(require_rule(rules, "price_position.pre_breakout_return_90d_max")):
        score += 16
    elif return_90d <= float(require_rule(rules, "price_position.max_return_90d_broad")):
        score += 6

    base_low = float(require_rule(rules, "classification.pre_breakout_close_to_base_high_min"))
    base_ideal_high = float(require_rule(rules, "classification.pre_breakout_close_to_base_high_ideal_max"))
    base_max = float(require_rule(rules, "classification.pre_breakout_close_to_base_high_max"))
    if base_low <= close_to_base_high_ratio <= base_ideal_high:
        score += 20
    elif base_ideal_high < close_to_base_high_ratio <= base_max:
        score += 10

    if abs(close_from_ema20_pct) <= float(require_rule(rules, "ema.setup_close_distance_ideal_abs")):
        score += 14
    elif close_from_ema20_pct <= float(require_rule(rules, "ema.setup_close_distance_max")):
        score += 6

    if close_from_base_low_pct <= float(require_rule(rules, "classification.pre_breakout_close_from_base_low_max")):
        score += 8
    return _clamp_score(score)


def _score_ema_micro_upturn(
    ema_spread: float,
    close_from_ema20_pct: float,
    ema5: float,
    ema10: float,
    ema5_slope: float,
    ema10_slope: float,
    ema20_slope: float,
    rules: dict[str, Any],
) -> int:
    score = 0
    if ema5_slope > float(require_rule(rules, "ema.ema5_micro_upturn_min")):
        score += 24
    if ema10_slope > float(require_rule(rules, "ema.ema10_flat_floor")):
        score += 18
    if ema20_slope > float(require_rule(rules, "ema.ema20_flat_floor")):
        score += 16
    if ema_spread < float(require_rule(rules, "ema.medium_spread")):
        score += 16
    elif ema_spread < float(require_rule(rules, "ema.initial_move_spread")):
        score += 10
    if abs(close_from_ema20_pct) <= float(require_rule(rules, "ema.setup_close_distance_ideal_abs")):
        score += 14
    elif close_from_ema20_pct <= float(require_rule(rules, "ema.setup_close_distance_max")):
        score += 6
    ema5_to_ema10_gap = abs(_safe_ratio(ema5 - ema10, ema10, 0.0))
    if ema5 >= ema10:
        score += 12
    elif ema5_to_ema10_gap <= float(require_rule(rules, "ema.medium_spread")):
        score += 8
    return _clamp_score(score)


def _compute_recent_base(close_series, volume_series) -> tuple[int, int, float, float]:
    """Rolling base detection — scan last 20/30/40 bars and pick the tightest+most-contracting window.

    Returns (best_score, window_size_bars, range_pct, contraction_ratio).
    Detects 「盤整尾端」at the end of the price series, regardless of where the legacy
    -60:-19 base window sits. Used as a bonus signal, not a hard gate.
    """
    if len(close_series) < 25:
        return (0, 0, 0.0, 1.0)
    best = (0, 0, 0.0, 1.0)
    for w in (20, 30, 40):
        if len(close_series) < w + 1:
            continue
        sub_close = close_series.iloc[-w - 1 : -1]
        sub_vol = volume_series.iloc[-w - 1 : -1]
        sub_high = float(sub_close.max())
        sub_low = float(sub_close.min())
        if sub_low <= 0:
            continue
        range_pct = (sub_high - sub_low) / sub_low
        first_half_vol = float(sub_vol.iloc[: w // 2].mean())
        second_half_vol = float(sub_vol.iloc[w // 2 :].mean())
        contraction = second_half_vol / first_half_vol if first_half_vol > 0 else 1.0
        score = 0
        # Range tightness (max 50)
        if range_pct < 0.08:
            score += 50
        elif range_pct < 0.12:
            score += 35
        elif range_pct < 0.18:
            score += 20
        # Volume contraction (max 50)
        if contraction <= 0.80:
            score += 50
        elif contraction <= 1.00:
            score += 30
        elif contraction <= 1.15:
            score += 10
        if score > best[0]:
            best = (score, w, round(range_pct, 4), round(contraction, 4))
    return best


def _score_volume_setup(volume_recovery_ratio_5d: float, volume_contraction_ratio: float, rules: dict[str, Any]) -> int:
    score = 0
    if volume_contraction_ratio < float(require_rule(rules, "base.contraction_ratio")):
        score += 38
    elif volume_contraction_ratio < float(require_rule(rules, "base.neutral_contraction_ratio")):
        score += 28
    elif volume_contraction_ratio < float(require_rule(rules, "base.expansion_ratio")):
        score += 18
    else:
        score += 8

    setup_min = float(require_rule(rules, "volume.setup_recovery_min"))
    setup_max = float(require_rule(rules, "volume.setup_recovery_max"))
    strong = float(require_rule(rules, "volume.strong_recovery_ratio"))
    overexpanded = float(require_rule(rules, "volume.overexpanded_recovery_ratio"))
    if setup_min <= volume_recovery_ratio_5d <= setup_max:
        score += 42
    elif setup_max < volume_recovery_ratio_5d <= strong:
        score += 28
    elif strong < volume_recovery_ratio_5d <= overexpanded:
        score += 12
    elif volume_recovery_ratio_5d >= float(require_rule(rules, "volume.weak_recovery_ratio")):
        score += 18
    else:
        score += 6
    return _clamp_score(score)


def _score_relative_strength(
    relative_strength_20d: Optional[float],
    relative_strength_60d: Optional[float],
    downside_resilience_20d: Optional[float],
    rules: dict[str, Any],
) -> int:
    if relative_strength_20d is None or relative_strength_60d is None:
        return int(require_rule(rules, "relative_strength.missing_score"))
    score = 40
    if relative_strength_20d > 0:
        score += 20
    if relative_strength_60d > 0:
        score += 20
    if relative_strength_20d > 0 and relative_strength_60d > 0:
        score += 10
    if relative_strength_20d > float(require_rule(rules, "relative_strength.strong_20d")):
        score += 5
    if relative_strength_60d > float(require_rule(rules, "relative_strength.high_60d")):
        score += 5
    if relative_strength_20d <= 0 and relative_strength_60d <= 0:
        score -= 10
    if downside_resilience_20d is not None:
        if downside_resilience_20d >= float(require_rule(rules, "relative_strength.downside_resilience_high")):
            score += 10
        elif downside_resilience_20d >= float(require_rule(rules, "relative_strength.downside_resilience_medium")):
            score += 5
    return _clamp_score(score)


def _risk_score(
    return_60d: float,
    return_5d: float,
    close_distance_from_ema20: float,
    upper_shadow_ratio_today: float,
    risk_flags: list[str],
    rules: dict[str, Any],
) -> int:
    score = 30
    if return_60d > float(require_rule(rules, "classification.overheat_return_60d")):
        score += 10
    if return_5d > float(require_rule(rules, "price_position.overheat_return_5d")):
        score += 25
    elif return_5d >= float(require_rule(rules, "price_position.warm_return_5d")):
        score += 15

    if close_distance_from_ema20 > float(require_rule(rules, "ema.extended_from_ema20")):
        score += 20
    elif close_distance_from_ema20 >= float(require_rule(rules, "ema.warm_extended_from_ema20")):
        score += 10

    if "high_upper_shadow_with_volume" in risk_flags:
        score += 20
    if "volume_climax" in risk_flags:
        score += 15
    if "low_liquidity" in risk_flags:
        score += 15
    if upper_shadow_ratio_today > float(require_rule(rules, "candle.upper_shadow_ratio")):
        score += 10
    return _clamp_score(score)


def _confidence_score(missing_data: list[str], data_quality_flags: list[str], rules: dict[str, Any]) -> int:
    score = int(require_rule(rules, "confidence.base"))
    if "universe_size_estimated" in data_quality_flags:
        score -= int(require_rule(rules, "confidence.universe_size_estimated_penalty"))

    caps: list[int] = []
    if "market_index" in missing_data:
        caps.append(int(require_rule(rules, "confidence.market_index_missing_cap")))
    if "turnover_value_estimated" in data_quality_flags:
        caps.append(int(require_rule(rules, "confidence.turnover_estimated_cap")))
    if "insufficient_history" in data_quality_flags:
        caps.append(int(require_rule(rules, "confidence.insufficient_history_cap")))
    if "yfinance_only_mode" in data_quality_flags:
        caps.append(75)
    if "mock_ohlcv" in data_quality_flags:
        caps.append(40)
    if caps:
        score = min(score, min(caps))
    return _clamp_score(score)


def _final_score(scores: CandidateScores, risk_score: int, rules: dict[str, Any]) -> int:
    weights = require_rule(rules, "scoring.weights")
    value = (
        scores.liquidity_score * float(weights["liquidity_score"])
        + scores.price_position_score * float(weights["price_position_score"])
        + scores.base_compression_score * float(weights["base_compression_score"])
        + scores.volume_score * float(weights["volume_score"])
        + scores.ema_convergence_score * float(weights["ema_convergence_score"])
        + scores.relative_strength_score * float(weights["relative_strength_score"])
        + risk_score * float(weights["risk_score"])
    )
    return _clamp_score(value)


def _score_ema_down_to_up_transition(
    ema5_slope_5d: float,
    ema5_slope_prev_10d: float,
    ema10_slope_5d: float,
    ema10_slope_prev_10d: float,
    ema20_slope_10d: float,
    ema20_slope_prev_20d: float,
    ema_spread: float,
    close_from_ema20_pct: float,
    rules: dict[str, Any],
) -> int:
    """EMA 由弱轉強訊號 — 前期下彎 / 走平，近期翻為上翹。
    完整多頭排列的股票 prev slopes 都是正的，會拿不到核心 75 分 (EMA5/10/20 三項)，
    所以這個 score 真正獎勵的是「轉折」型態，不是「持續多頭」。
    """
    score = 0
    # EMA5 — 前期下彎或走平，近期明確上彎 (+30)
    if ema5_slope_prev_10d <= 0 and ema5_slope_5d > 0:
        score += 30
    # EMA10 — 前期下彎或走平，近期走平或微上 (+25)
    if ema10_slope_prev_10d <= 0 and ema10_slope_5d > -0.001:
        score += 25
    # EMA20 — 前期下彎，近期不明顯下彎 (止跌訊號) (+20)
    if ema20_slope_prev_20d < 0 and ema20_slope_10d > -0.003:
        score += 20
    # 三條 EMA 糾結 (+15)
    if ema_spread <= 0.05:
        score += 15
    # 價格貼近 EMA20 兩個方向都要近 (+10)
    if abs(close_from_ema20_pct) <= 0.08:
        score += 10
    return _clamp_score(score)


def _score_volume_contraction(volume_contraction_ratio: float, rules: dict[str, Any]) -> int:
    """純 volume_contraction_ratio 評分 — 起漲前觀察專屬。

    ratio = base 後半 20日均量 / base 前半 20日均量。越小越好（量越乾）。
    """
    if volume_contraction_ratio <= 0.85:
        return 90        # 理想縮量
    if volume_contraction_ratio <= 1.00:
        return 65        # 可接受縮量
    if volume_contraction_ratio <= 1.15:
        return 40        # 普通 (沒縮也沒爆)
    return 20            # 盤整期沒縮量 → 不是真盤整


def _final_pre_breakout_score(
    base_compression_score: int,
    ema_micro_upturn_score: int,
    ema_down_to_up_transition_score: int,
    setup_price_position_score: int,
    volume_contraction_score: int,
    relative_strength_score: int,
    liquidity_score: int,
    risk_score: int,
    rules: dict[str, Any],
) -> int:
    weights = require_rule(rules, "scoring.pre_breakout_weights")
    value = (
        base_compression_score * float(weights["base_compression_score"])
        + ema_micro_upturn_score * float(weights["ema_micro_upturn_score"])
        + ema_down_to_up_transition_score * float(weights["ema_down_to_up_transition_score"])
        + setup_price_position_score * float(weights["setup_price_position_score"])
        + volume_contraction_score * float(weights["volume_contraction_score"])
        + relative_strength_score * float(weights["relative_strength_score"])
        + liquidity_score * float(weights["liquidity_score"])
        + risk_score * float(weights["risk_score"])
    )
    return _clamp_score(value)


def _format_pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _build_reasons(metrics: CandidateMetrics, rules: dict[str, Any]) -> list[str]:
    reasons = [
        f"近三個月（約 63 個交易日）漲幅 {_format_pct(metrics.return_90d or 0.0)}，顯示中期積累趨勢，且近一個月漲幅 {_format_pct(metrics.return_20d)} 仍屬盤整，尚未進入啟動段",
        f"近 60 日漲幅 {_format_pct(metrics.return_60d)}",
        f"前 60-20 日盤整期漲跌幅僅 {_format_pct(metrics.return_60_to_20)}，符合初動前整理特徵",
        f"盤整後半段成交量縮減至前半段的 {metrics.volume_contraction_ratio:.0%}，近期量能開始回溫",
        f"EMA5/EMA10/EMA20 糾結度 {metrics.ema_spread:.1%}，且開始向上",
        f"流動性充足（20 日均量 {metrics.avg_volume_20_lots:,.0f} 張）",
    ]
    if metrics.relative_strength_20d is not None and metrics.relative_strength_20d > 0:
        reasons.append(f"近 20 日表現強於加權指數 {_format_pct(metrics.relative_strength_20d)}")
    if metrics.relative_strength_60d is not None and metrics.relative_strength_60d > 0:
        reasons.append(f"近 60 日表現強於加權指數 {_format_pct(metrics.relative_strength_60d)}")
    return reasons


def _build_watch_conditions(metrics: CandidateMetrics) -> list[str]:
    return [
        f"是否帶量突破整理區高點 {metrics.base_high:.2f}",
        "是否維持在 EMA5/10/20 之上",
        "大盤回檔時是否仍保持抗跌",
        "量能是否溫和放大而非爆量收長上影",
        "近 20 日相對強勢是否延續",
    ]


def _build_invalidation(metrics: CandidateMetrics) -> list[str]:
    return [
        f"收盤跌破整理區下緣 {metrics.base_low:.2f}",
        "跌破 EMA20 且無法收回",
        "放量但價格無法突破整理區高點",
        "出現爆量長上影線（爆量後收盤位於日內中下段）",
        "近 20 日相對強勢轉弱（relative_strength_20d < 0）",
    ]


def _compute_entry_tier(
    features: dict[str, Any],
    rules: dict[str, Any],
    risk_score: int,
) -> int:
    """Phase 11: return 0=no entry, 1=CORE, 2=QUALITY, 3=PREMIUM.

    This is an additive backtest/sizing signal. It keeps the Flat Base identity
    locked by enforcing the non-negotiable structure gates before assigning any
    tier, then lets quality filters upgrade the position.
    """
    pp = rules.get("price_position", {})
    cls = rules.get("classification", {})

    range_min = max(float(pp.get("pre_breakout_range_90d_min", 0.10)), 0.10)
    range_max = min(float(pp.get("pre_breakout_range_90d_max", 0.30)), 0.30)
    r90 = float(features.get("range_90d", 0.0))
    if not (range_min <= r90 <= range_max):
        return 0

    if float(features.get("volume_contraction_ratio", 99.0)) > 1.0:
        return 0

    # Core invariant: still require EMA cluster not to be fully fanned out.
    if float(features.get("ema_spread", 99.0)) > 0.08:
        return 0

    base_high = float(features.get("base_high", 0.0))
    close_today = float(features.get("close_today", 0.0))
    breakout_buffer = float(cls.get("breakout_pivot_buffer", 0.001))
    if base_high <= 0 or close_today <= base_high * (1.0 + breakout_buffer):
        return 0

    if float(features.get("close_to_base_high_ratio", 99.0)) > 1.08:
        return 0

    if float(features.get("avg_turnover_20", 0.0)) < 30_000_000:
        return 0

    if float(features.get("return_90d", -99.0)) < -0.25:
        return 0

    tier = 1

    avg_volume_50 = float(features.get("avg_volume_50_shares", 0.0))
    volume_today = float(features.get("volume_today_shares", 0.0))
    tier2_pass = (
        float(features.get("ema_spread", 99.0)) <= 0.05
        and float(features.get("ema5_slope", -99.0)) >= 0.0
        and float(features.get("ema10_slope", -99.0)) >= 0.0
        and float(features.get("ema20_slope", -99.0)) >= 0.0
        and float(features.get("base_range_pct", 99.0)) <= 0.15
        and avg_volume_50 > 0
        and volume_today >= avg_volume_50 * 1.2
        and int(features.get("pre_breakout_score", 0)) >= 50
        and int(features.get("ema_micro_upturn_score", 0)) >= 40
        and risk_score < 70
    )
    if tier2_pass:
        tier = 2

    if tier == 2:
        tier3_pass = (
            avg_volume_50 > 0
            and volume_today >= avg_volume_50 * 1.5
            and int(features.get("pre_breakout_score", 0)) >= 60
            and int(features.get("ema_micro_upturn_score", 0)) >= 60
            and int(features.get("base_compression_score", 0)) >= 60
            and int(features.get("ema_down_to_up_transition_score", 0)) >= 50
            and float(features.get("avg_turnover_20", 0.0)) >= 100_000_000
            and bool(features.get("trend_template_ok", False))
        )
        if tier3_pass:
            tier = 3

    return tier


def _classify_candidate(
    score: int,
    risk_score: int,
    risk_flags: list[str],
    condition_gates: dict[str, bool],
    metrics: CandidateMetrics,
    scores: CandidateScores,
    bullish_stack: bool,
    rules: dict[str, Any],
) -> str:
    positive_signs = 0
    if metrics.return_60d >= float(require_rule(rules, "price_position.low_return_60d_max")) or metrics.return_20d >= float(require_rule(rules, "price_position.medium_return_20d")):
        positive_signs += 1
    if scores.base_compression_score >= int(require_rule(rules, "classification.initial_base_score_min")):
        positive_signs += 1
    if condition_gates.get("ema_micro_upturn", False) or scores.ema_convergence_score >= int(require_rule(rules, "classification.initial_ema_score_min")):
        positive_signs += 1
    if (
        metrics.relative_strength_20d is not None
        and metrics.relative_strength_60d is not None
        and (metrics.relative_strength_20d > 0 or metrics.relative_strength_60d > 0)
    ):
        positive_signs += 1

    if (
        metrics.return_20d > float(require_rule(rules, "price_position.max_return_20d_not_surged"))
        or (metrics.return_90d is not None and metrics.return_90d > float(require_rule(rules, "price_position.max_return_90d_broad")))
        # 偏熱閾值收緊：close 距 EMA20 > 8% 就視為偏熱 (從 15% 改成 8%)
        or metrics.close_from_ema20_pct > float(require_rule(rules, "ema.overheated_close_ema20_min"))
        # 新增：EMA 糾結度 > 5% 也視為偏熱 (EMA 已分叉)
        or metrics.ema_spread > float(require_rule(rules, "ema.overheated_ema_spread_min"))
        or metrics.return_60d > float(require_rule(rules, "classification.overheat_return_60d"))
        or metrics.return_5d > float(require_rule(rules, "price_position.overheat_return_5d"))
        or risk_score >= int(require_rule(rules, "classification.overheat_risk_score"))
        or "high_upper_shadow_with_volume" in risk_flags
        or "extended_from_ema20" in risk_flags
    ):
        return "偏熱觀察"

    if (
        "low_liquidity" in risk_flags
        or not condition_gates.get("liquidity", False)
        or not condition_gates.get("price_position", False)
        or not condition_gates.get("return_5d_not_extreme", True)
        or not condition_gates.get("return_90d_range", True)
        or not condition_gates.get("volume_not_dried_up", True)
        # close_not_far_from_ema20 / ema_not_spread_out 不再是「不符合」硬閘 —
        # 它們是起漲前觀察專屬的精準篩選條件。已被起漲前 block 內部直接 enforce。
        # 把這兩個從 不符合 拿掉，初動候選 / 動能確認等才能正常分類。
        or condition_gates.get("severe_data_error", False)
        or positive_signs == 0
    ):
        return "不符合"

    if (
        metrics.pre_breakout_score >= int(require_rule(rules, "classification.pre_breakout_score_min"))
        # 20 日 / 60 日漲幅 — 嚴格收緊，起漲前 = 還沒動
        and metrics.return_20d <= float(require_rule(rules, "price_position.pre_breakout_return_20d_strict_max"))
        and metrics.return_60d <= float(require_rule(rules, "price_position.pre_breakout_return_60d_strict_max"))
        # 90 日擺盪幅度 10~30% — 主力表態 → 回調洗浮盈 → 蓄勢待發 Bull Flag
        and metrics.range_90d >= float(require_rule(rules, "price_position.pre_breakout_range_90d_min"))
        and metrics.range_90d <= float(require_rule(rules, "price_position.pre_breakout_range_90d_max"))
        # 輔助過濾：避免「跌完反彈」型態 (return_90d 不能太負)
        and metrics.return_90d is not None
        and metrics.return_90d >= float(require_rule(rules, "price_position.pre_breakout_return_90d_min"))
        # abs(close-EMA20)/EMA20 ≤ 5% — 不允許價遠離 EMA20 (兩個方向都要近)
        and abs(metrics.close_from_ema20_pct) <= float(require_rule(rules, "ema.pre_breakout_close_ema20_max"))
        # 不可超過基底高點 (突破已經發生的擋掉)
        and metrics.close_to_base_high_ratio <= float(require_rule(rules, "classification.pre_breakout_close_to_base_high_max"))
        and metrics.close_from_base_low_pct <= float(require_rule(rules, "classification.pre_breakout_close_from_base_low_max"))
        # EMA 糾結度 ≤ 3% 硬閘
        and metrics.ema_spread <= float(require_rule(rules, "ema.pre_breakout_ema_spread_max"))
        # 3 條 EMA 斜率 — 不只看 score，直接硬閘
        and metrics.ema5_slope > float(require_rule(rules, "ema.ema5_micro_upturn_min"))
        and metrics.ema10_slope > float(require_rule(rules, "ema.ema10_flat_floor"))
        and metrics.ema20_slope > float(require_rule(rules, "ema.ema20_flat_floor"))
        and metrics.ema_micro_upturn_score >= int(require_rule(rules, "classification.pre_breakout_ema_score_min"))
        and scores.base_compression_score >= int(require_rule(rules, "classification.pre_breakout_base_score_min"))
        # EMA 由弱轉強 — 過濾掉「已經完整多頭排列、長期上漲」型 (它們 prev slope 都是正的，拿不到此分)
        and metrics.ema_down_to_up_transition_score >= int(require_rule(rules, "classification.pre_breakout_ema_transition_score_min"))
        # 真正縮量 ≤ 80%
        and metrics.volume_contraction_ratio <= float(require_rule(rules, "volume.pre_breakout_volume_contraction_max"))
        # 熱門股要求 — 20 日均量金額 ≥ 1 億 (避免冷門小型股摻入)
        and metrics.avg_turnover_20 >= float(require_rule(rules, "classification.pre_breakout_min_turnover"))
        and risk_score < int(require_rule(rules, "classification.pre_breakout_risk_score_max"))
        # Phase 9.8 (O'Neil Flat Base event trigger): 突破當日 + 量 ≥ 1.4× 50 日均量
        and condition_gates.get("breakout_today", False)
        # Phase 9.8 (O'Neil Flat Base structure): base 整理深度 ≤ 15%
        and condition_gates.get("base_depth_ok", False)
    ):
        return "起漲前觀察"

    if score < int(require_rule(rules, "classification.disqualify_score_below")):
        return "不符合"

    if (
        score >= int(require_rule(rules, "classification.momentum_score_min"))
        and metrics.volume_recovery_ratio_5d >= float(require_rule(rules, "volume.sustained_recovery_ratio"))
        and condition_gates.get("close_above_ema20", False)
        and (
            condition_gates.get("close_above_ema10", False)
            or condition_gates.get("close_above_ema5", False)
        )
        and (metrics.relative_strength_20d is None or metrics.relative_strength_20d > 0)
    ):
        return "動能確認"

    if (
        score >= int(require_rule(rules, "classification.initial_score_min"))
        and risk_score < int(require_rule(rules, "classification.initial_risk_score_max"))
        and scores.base_compression_score >= int(require_rule(rules, "classification.initial_base_score_min"))
        and scores.ema_convergence_score >= int(require_rule(rules, "classification.initial_ema_score_min"))
        and scores.volume_score >= int(require_rule(rules, "classification.initial_volume_score_min"))
    ):
        return "初動候選"

    if (
        score >= int(require_rule(rules, "classification.observation_score_min"))
        and risk_score < int(require_rule(rules, "classification.observation_risk_score_max"))
        and positive_signs >= int(require_rule(rules, "classification.observation_positive_signs_min"))
    ):
        return "初動觀察"

    return "不符合"


def _compute_base_features(
    normalized: pd.DataFrame,
    df_market: Optional[pd.DataFrame],
    rules: dict[str, Any],
    *,
    data_quality_flags: list[str],
    missing_data: list[str],
    market_index_source: str = "unavailable",
) -> dict[str, Any]:
    """Compute all param-independent point-in-time features.

    "Param-independent" here means: the rule keys consumed inside this function
    (return_90d_lookback_bars, lots_per_share, initial_move_spread,
    ema5_micro_upturn_min, ema10_flat_floor, ema20_flat_floor,
    overheat_return_5d, upper_shadow_ratio, upper_shadow_volume_ratio,
    climax_volume_ratio, weak_close_position, extended_from_ema20) are NEVER
    in the optimizer's search space, so the returned features are stable across
    all trials of one optimization session and safe to cache by (stock_id,
    as_of_date).

    The function MUTATES `data_quality_flags` and `missing_data` to record
    side-effect flags such as "ema_history_insufficient" or "market_index".
    The returned dict ALSO records these additions under `_data_quality_flags`
    and `_missing_data` so a cached version can replay them on later calls.
    """
    # Track what THIS call appends so we can serialize the side-effects.
    added_quality_flags: list[str] = []
    added_missing_data: list[str] = []

    def _append_quality_flag(flag: str) -> None:
        data_quality_flags.append(flag)
        added_quality_flags.append(flag)

    def _append_missing(name: str) -> None:
        missing_data.append(name)
        added_missing_data.append(name)

    close_today = float(normalized["close"].iloc[-1])
    close_60d = float(normalized["close"].iloc[-60])
    close_20d = float(normalized["close"].iloc[-20])
    close_5d = float(normalized["close"].iloc[-5])
    lookback_90d = min(int(require_rule(rules, "price_position.return_90d_lookback_bars")), len(normalized) - 1)
    close_90d = float(normalized["close"].iloc[-lookback_90d])
    return_60d = _safe_ratio(close_today - close_60d, close_60d)
    return_90d = _safe_ratio(close_today - close_90d, close_90d)
    return_20d = _safe_ratio(close_today - close_20d, close_20d)
    return_5d = _safe_ratio(close_today - close_5d, close_5d)
    return_60_to_20 = _safe_ratio(close_20d - close_60d, close_60d)
    # 90 日擺盪幅度 — high/low (Bull Flag 整理區間)
    window_90d = normalized.tail(lookback_90d)
    high_90d = float(window_90d["high"].max())
    low_90d = float(window_90d["low"].min())
    range_90d = _safe_ratio(high_90d - low_90d, low_90d)

    base_period = normalized.iloc[-60:-19]
    base_high = float(base_period["close"].max())
    base_low = float(base_period["close"].min())
    recent_base_score, recent_base_window_bars, recent_base_range_pct, recent_base_contraction_ratio = (
        _compute_recent_base(normalized["close"], normalized["volume"])
    )
    base_range_pct = _safe_ratio(base_high - base_low, base_low)

    lots_per_share = float(require_rule(rules, "volume.lots_per_share"))
    volume_today_shares = float(normalized["volume"].iloc[-1])
    avg_volume_5_shares = float(normalized["volume"].tail(5).mean())
    avg_volume_20_shares = float(normalized["volume"].tail(20).mean())
    # 50-day average volume — O'Neil breakout standard reference (≥ 1.4× = institutional buying)
    _vol_50_window = min(50, len(normalized))
    avg_volume_50_shares = float(normalized["volume"].tail(_vol_50_window).mean())
    avg_volume_20_lots = avg_volume_20_shares / lots_per_share
    avg_turnover_20 = float(normalized["turnover_value"].tail(20).mean())

    base_volume_first_shares = float(normalized["volume"].iloc[-60:-40].mean())
    base_volume_second_shares = float(normalized["volume"].iloc[-40:-19].mean())
    volume_contraction_ratio = _safe_ratio(base_volume_second_shares, base_volume_first_shares, 1.0)
    volume_recovery_ratio_5d = _safe_ratio(avg_volume_5_shares, avg_volume_20_shares, 1.0)
    volume_today_ratio_20 = _safe_ratio(volume_today_shares, avg_volume_20_shares, 1.0)

    ema5_series = _ema(normalized["close"], 5)
    ema10_series = _ema(normalized["close"], 10)
    ema20_series = _ema(normalized["close"], 20)
    ema5 = float(ema5_series.iloc[-1])
    ema10 = float(ema10_series.iloc[-1])
    ema20 = float(ema20_series.iloc[-1])
    ema_spread = _safe_ratio(max(ema5, ema10, ema20) - min(ema5, ema10, ema20), close_today)
    ema5_slope = _safe_ratio(ema5 - float(ema5_series.iloc[-5]), float(ema5_series.iloc[-5]))
    ema10_slope = _safe_ratio(ema10 - float(ema10_series.iloc[-5]), float(ema10_series.iloc[-5]))
    ema20_slope = _safe_ratio(ema20 - float(ema20_series.iloc[-10]), float(ema20_series.iloc[-10]))
    trend_template_ok = False
    if len(normalized) >= 200:
        ema50_series = _ema(normalized["close"], 50)
        ema150_series = _ema(normalized["close"], 150)
        ema200_series = _ema(normalized["close"], 200)
        ema50_last = float(ema50_series.iloc[-1])
        ema150_last = float(ema150_series.iloc[-1])
        ema200_last = float(ema200_series.iloc[-1])
        ema200_valid = ema200_series.dropna()
        ema200_reference = float(ema200_valid.iloc[-30] if len(ema200_valid) >= 30 else ema200_valid.iloc[0])
        trend_template_ok = (
            not pd.isna(ema50_last)
            and not pd.isna(ema150_last)
            and not pd.isna(ema200_last)
            and close_today > ema50_last
            and ema50_last > ema150_last
            and ema150_last > ema200_last
            and ema200_last > ema200_reference
        )
    try:
        ema5_slope_prev_10d = _safe_ratio(
            float(ema5_series.iloc[-5]) - float(ema5_series.iloc[-15]),
            float(ema5_series.iloc[-15]),
        )
        ema10_slope_prev_10d = _safe_ratio(
            float(ema10_series.iloc[-5]) - float(ema10_series.iloc[-15]),
            float(ema10_series.iloc[-15]),
        )
        ema20_slope_prev_20d = _safe_ratio(
            float(ema20_series.iloc[-10]) - float(ema20_series.iloc[-30]),
            float(ema20_series.iloc[-30]),
        )
    except (IndexError, ValueError):
        ema5_slope_prev_10d = 0.0
        ema10_slope_prev_10d = 0.0
        ema20_slope_prev_20d = 0.0
        _append_quality_flag("ema_history_insufficient")
    bullish_stack = ema5 > ema10 > ema20
    close_above_all_emas = close_today >= ema5 and close_today >= ema10 and close_today >= ema20
    ema_near_convergence = ema_spread < float(require_rule(rules, "ema.initial_move_spread"))
    ema_micro_upturn = (
        ema5_slope > float(require_rule(rules, "ema.ema5_micro_upturn_min"))
        and ema10_slope > float(require_rule(rules, "ema.ema10_flat_floor"))
        and ema20_slope > float(require_rule(rules, "ema.ema20_flat_floor"))
    )

    relative_strength_20d: Optional[float]
    relative_strength_60d: Optional[float]
    downside_resilience_20d: Optional[float]
    try:
        if df_market is None or df_market.empty or len(df_market) < int(require_rule(rules, "history.minimum_days")):
            raise ValueError("market index unavailable")
        market_df, _ = _canonicalize_ohlcv(df_market)
        if len(market_df) < int(require_rule(rules, "history.minimum_days")):
            raise ValueError("market index insufficient")
        market_close_today = float(market_df["close"].iloc[-1])
        market_return_20d = _safe_ratio(market_close_today - float(market_df["close"].iloc[-20]), float(market_df["close"].iloc[-20]))
        market_return_60d = _safe_ratio(market_close_today - float(market_df["close"].iloc[-60]), float(market_df["close"].iloc[-60]))
        relative_strength_20d = return_20d - market_return_20d
        relative_strength_60d = return_60d - market_return_60d

        stock_daily_returns = normalized["close"].pct_change().tail(20).reset_index(drop=True)
        market_daily_returns = market_df["close"].pct_change().tail(20).reset_index(drop=True)
        overlap = min(len(stock_daily_returns), len(market_daily_returns))
        downside_days = 0
        resilient_days = 0
        for stock_return, market_return in zip(stock_daily_returns.tail(overlap), market_daily_returns.tail(overlap)):
            if pd.isna(stock_return) or pd.isna(market_return):
                continue
            if float(market_return) < 0:
                downside_days += 1
                if float(stock_return) >= float(market_return):
                    resilient_days += 1
        downside_resilience_20d = resilient_days / downside_days if downside_days else None
    except Exception:
        relative_strength_20d = None
        relative_strength_60d = None
        downside_resilience_20d = None
        _append_missing("market_index")
        market_index_source = "unavailable"

    high_today = float(normalized["high"].iloc[-1])
    low_today = float(normalized["low"].iloc[-1])
    open_today = float(normalized["open"].iloc[-1])
    daily_range = high_today - low_today
    upper_shadow_ratio_today = _safe_ratio(high_today - max(open_today, close_today), daily_range, 0.0)
    close_position_in_range = _safe_ratio(close_today - low_today, daily_range, 0.5)
    close_distance_from_ema20 = _safe_ratio(close_today, ema20, 1.0) - 1
    close_from_ema20_pct = close_distance_from_ema20
    close_to_base_high_ratio = _safe_ratio(close_today, base_high, 1.0)
    close_from_base_low_pct = _safe_ratio(close_today, base_low, 1.0) - 1

    risk_flags: list[str] = []
    if return_5d > float(require_rule(rules, "price_position.overheat_return_5d")):
        risk_flags.append("parabolic_rise_5d")
    if upper_shadow_ratio_today > float(require_rule(rules, "candle.upper_shadow_ratio")) and volume_today_ratio_20 > float(require_rule(rules, "volume.upper_shadow_volume_ratio")):
        risk_flags.append("high_upper_shadow_with_volume")
    if volume_today_ratio_20 > float(require_rule(rules, "volume.climax_volume_ratio")) and close_position_in_range < float(require_rule(rules, "candle.weak_close_position")):
        risk_flags.append("volume_climax")
    if close_distance_from_ema20 > float(require_rule(rules, "ema.extended_from_ema20")):
        risk_flags.append("extended_from_ema20")
    # market_index_missing risk flag is appended later (it depends on low_liquidity which is param-dep)

    return {
        # Returns
        "return_60d": return_60d, "return_90d": return_90d, "return_20d": return_20d,
        "return_5d": return_5d, "return_60_to_20": return_60_to_20,
        # Range / base
        "high_90d": high_90d, "low_90d": low_90d, "range_90d": range_90d,
        "lookback_90d": lookback_90d,
        "base_high": base_high, "base_low": base_low, "base_range_pct": base_range_pct,
        "recent_base_score": recent_base_score,
        "recent_base_window_bars": recent_base_window_bars,
        "recent_base_range_pct": recent_base_range_pct,
        "recent_base_contraction_ratio": recent_base_contraction_ratio,
        # Prices
        "close_today": close_today, "high_today": high_today, "low_today": low_today,
        "open_today": open_today,
        # Volume
        "lots_per_share": lots_per_share,
        "volume_today_shares": volume_today_shares,
        "avg_volume_5_shares": avg_volume_5_shares,
        "avg_volume_20_shares": avg_volume_20_shares,
        "avg_volume_50_shares": avg_volume_50_shares,
        "avg_volume_20_lots": avg_volume_20_lots,
        "avg_turnover_20": avg_turnover_20,
        "base_volume_first_shares": base_volume_first_shares,
        "base_volume_second_shares": base_volume_second_shares,
        "volume_contraction_ratio": volume_contraction_ratio,
        "volume_recovery_ratio_5d": volume_recovery_ratio_5d,
        "volume_today_ratio_20": volume_today_ratio_20,
        # EMA
        "ema5": ema5, "ema10": ema10, "ema20": ema20,
        "ema_spread": ema_spread,
        "ema5_slope": ema5_slope, "ema10_slope": ema10_slope, "ema20_slope": ema20_slope,
        "ema5_slope_prev_10d": ema5_slope_prev_10d,
        "ema10_slope_prev_10d": ema10_slope_prev_10d,
        "ema20_slope_prev_20d": ema20_slope_prev_20d,
        "bullish_stack": bullish_stack,
        "close_above_all_emas": close_above_all_emas,
        "ema_near_convergence": ema_near_convergence,
        "ema_micro_upturn": ema_micro_upturn,
        "trend_template_ok": trend_template_ok,
        # Relative strength
        "relative_strength_20d": relative_strength_20d,
        "relative_strength_60d": relative_strength_60d,
        "downside_resilience_20d": downside_resilience_20d,
        # Daily candle
        "daily_range": daily_range,
        "upper_shadow_ratio_today": upper_shadow_ratio_today,
        "close_position_in_range": close_position_in_range,
        "close_distance_from_ema20": close_distance_from_ema20,
        "close_from_ema20_pct": close_from_ema20_pct,
        "close_to_base_high_ratio": close_to_base_high_ratio,
        "close_from_base_low_pct": close_from_base_low_pct,
        # Risk
        "risk_flags": risk_flags,
        # Pass-through state
        "market_index_source": market_index_source,
        # Serialized side-effects for cache replay
        "_data_quality_flags": added_quality_flags,
        "_missing_data": added_missing_data,
    }


def evaluate_surge_candidate(
    stock_id: str,
    stock_name: str,
    df: pd.DataFrame,
    df_market: Optional[pd.DataFrame] = None,
    *,
    parameters: Optional[ScreenerParameters] = None,
    include_unfit: bool = False,
    universe_size_estimated: bool = False,
    debug_context: Optional[dict[str, Any]] = None,
    source_info: Optional[dict[str, Any]] = None,
    market_index_source: str = "unavailable",
    precomputed_features: Optional[dict[str, Any]] = None,
) -> Optional[SurgeCandidateResult]:
    """Main screener entrypoint.

    Optimizer fast-path:
        If `precomputed_features` is provided (output of `_compute_base_features`
        keyed by (stock_id, as_of_date)), Stage 1 is skipped. Only Stage 2
        (rule application + classification) runs, which is ~5-10× faster.

        Caller MUST guarantee features were computed from the SAME df + df_market
        with rules whose param-independent shape keys (return_90d_lookback_bars,
        lots_per_share, initial_move_spread, ema*_micro_upturn / flat thresholds,
        overheat_return_5d, upper_shadow_*, climax_volume_ratio,
        weak_close_position, extended_from_ema20) are identical. The optimizer's
        search space never touches these keys, so cache reuse is safe across
        all trials in one optimization session.
    """
    rules = load_surge_candidate_rules()
    params = parameters or default_screener_parameters()

    if len(df) < int(require_rule(rules, "history.minimum_days")):
        return None

    data_quality_flags: list[str] = []
    missing_data: list[str] = []
    source_info_dict = dict(source_info or {})
    source_warnings = [str(item) for item in source_info_dict.get("data_warnings", [])]
    if len(df) < int(require_rule(rules, "history.full_confidence_days")):
        data_quality_flags.append("insufficient_history")
    if universe_size_estimated:
        data_quality_flags.append("universe_size_estimated")
    for warning in source_warnings:
        if warning in {"mock_ohlcv", "yfinance_only_mode", "turnover_value_estimated"} and warning not in data_quality_flags:
            data_quality_flags.append(warning)

    normalized, has_turnover = _canonicalize_ohlcv(df)
    if len(normalized) < int(require_rule(rules, "history.minimum_days")):
        return None

    if not has_turnover:
        normalized["turnover_value"] = normalized["close"] * normalized["volume"]
        missing_data.append("turnover_value")
        data_quality_flags.append("turnover_value_estimated")
        source_info_dict["turnover_source"] = "estimated"
    elif not source_info_dict.get("turnover_source"):
        source_info_dict["turnover_source"] = "official" if "tpex_official_latest" in source_warnings else "finmind_trading_money"

    # ── Stage 1: param-independent feature computation (cacheable across trials) ──
    if precomputed_features is not None:
        features = precomputed_features
        # Merge cached side-effect lists into the per-call lists so downstream
        # logic sees them. Cached lists are short, dedup is cheap.
        for flag in features.get("_data_quality_flags", []):
            if flag not in data_quality_flags:
                data_quality_flags.append(flag)
        for item in features.get("_missing_data", []):
            if item not in missing_data:
                missing_data.append(item)
    else:
        features = _compute_base_features(
            normalized, df_market, rules,
            data_quality_flags=data_quality_flags,
            missing_data=missing_data,
            market_index_source=market_index_source,
        )
    # Unpack features into local vars so the rest of the function reads unchanged.
    return_60d = features["return_60d"]
    return_90d = features["return_90d"]
    return_20d = features["return_20d"]
    return_5d = features["return_5d"]
    return_60_to_20 = features["return_60_to_20"]
    high_90d = features["high_90d"]
    low_90d = features["low_90d"]
    range_90d = features["range_90d"]
    base_high = features["base_high"]
    base_low = features["base_low"]
    base_range_pct = features["base_range_pct"]
    recent_base_score = features["recent_base_score"]
    recent_base_window_bars = features["recent_base_window_bars"]
    recent_base_range_pct = features["recent_base_range_pct"]
    recent_base_contraction_ratio = features["recent_base_contraction_ratio"]
    close_today = features["close_today"]
    avg_volume_20_lots = features["avg_volume_20_lots"]
    avg_volume_50_shares = features["avg_volume_50_shares"]
    avg_turnover_20 = features["avg_turnover_20"]
    volume_today_shares = features["volume_today_shares"]
    volume_contraction_ratio = features["volume_contraction_ratio"]
    volume_recovery_ratio_5d = features["volume_recovery_ratio_5d"]
    volume_today_ratio_20 = features["volume_today_ratio_20"]
    ema5 = features["ema5"]
    ema10 = features["ema10"]
    ema20 = features["ema20"]
    ema_spread = features["ema_spread"]
    ema5_slope = features["ema5_slope"]
    ema10_slope = features["ema10_slope"]
    ema20_slope = features["ema20_slope"]
    ema5_slope_prev_10d = features["ema5_slope_prev_10d"]
    ema10_slope_prev_10d = features["ema10_slope_prev_10d"]
    ema20_slope_prev_20d = features["ema20_slope_prev_20d"]
    bullish_stack = features["bullish_stack"]
    close_above_all_emas = features["close_above_all_emas"]
    ema_near_convergence = features["ema_near_convergence"]
    ema_micro_upturn = features["ema_micro_upturn"]
    relative_strength_20d = features["relative_strength_20d"]
    relative_strength_60d = features["relative_strength_60d"]
    downside_resilience_20d = features["downside_resilience_20d"]
    upper_shadow_ratio_today = features["upper_shadow_ratio_today"]
    close_position_in_range = features["close_position_in_range"]
    close_distance_from_ema20 = features["close_distance_from_ema20"]
    close_from_ema20_pct = features["close_from_ema20_pct"]
    close_to_base_high_ratio = features["close_to_base_high_ratio"]
    close_from_base_low_pct = features["close_from_base_low_pct"]
    market_index_source = features["market_index_source"]
    # risk_flags is mutated below with low_liquidity + market_index_missing entries
    # (those depend on params and missing_data, which can only be checked here).
    risk_flags = list(features["risk_flags"])
    low_liquidity = avg_volume_20_lots < params.min_avg_volume_lots and avg_turnover_20 < params.min_avg_turnover
    if low_liquidity:
        risk_flags.append("low_liquidity")
    if "market_index" in missing_data:
        risk_flags.append("market_index_missing")

    condition_gates = {
        "price_position": params.min_return_60d <= return_60d <= params.max_return_60d,
        "base": (
            abs(return_60_to_20) <= float(require_rule(rules, "price_position.medium_base_return_abs"))
            or base_range_pct < float(require_rule(rules, "base.loose_range_pct"))
        ),
        "volume_recovery": (
            volume_recovery_ratio_5d > float(require_rule(rules, "volume.mild_recovery_ratio"))
            or volume_today_ratio_20 > float(require_rule(rules, "volume.single_day_surge_ratio"))
        ),
        "liquidity": not low_liquidity,
        "return_5d_not_extreme": return_5d < float(require_rule(rules, "price_position.parabolic_return_5d")),
        "ema": ema_near_convergence and ema_micro_upturn,
        "ema_near_convergence": ema_near_convergence,
        "ema_micro_upturn": ema_micro_upturn,
        "ema_price_above_all": close_above_all_emas,
        "close_above_ema5": close_today >= ema5,
        "close_above_ema10": close_today >= ema10,
        "close_above_ema20": close_today >= ema20,
        "ema_full_bullish_alignment": bullish_stack,
        "relative_strength": (
            "market_index" in missing_data
            or (
                relative_strength_20d is not None
                and relative_strength_60d is not None
                and relative_strength_20d > 0
                and relative_strength_60d > 0
            )
        ),
        "severe_data_error": False,
        # Broad hard filter: excludes stocks that are clearly negative or already overextended (>35%)
        "return_90d_range": (
            float(require_rule(rules, "price_position.min_return_90d_broad")) <= return_90d
            <= float(require_rule(rules, "price_position.max_return_90d_broad"))
        ),
        # Ideal zone for scoring reference: 10%–30% is the sweet-spot from hypothesis
        "return_90d_ideal_range": (
            float(require_rule(rules, "price_position.min_return_90d")) <= return_90d
            <= float(require_rule(rules, "price_position.max_return_90d"))
        ),
        # Liquidity guard: the 20-day average volume must meet minimum lot threshold.
        # NOTE: volume_contraction_ratio measures base-period shrinkage and is a POSITIVE scoring signal.
        # This gate only prevents completely illiquid / dead-fish stocks from passing through.
        "volume_not_dried_up": (
            avg_volume_20_lots >= float(require_rule(rules, "liquidity.min_avg_volume_20_lots"))
        ),
        # Diagnostic only — NOT a hard disqualifier. Tracks whether the last 20 days
        # haven't yet seen a large move, which is informational context only.
        "return_20d_pre_breakout": (
            return_20d < float(require_rule(rules, "price_position.pre_breakout_return_20d_max"))
        ),
        # Hard filter: stock must not have already surged > 15% in the last 20 days.
        # This preserves pre-breakout setups and avoids catching stocks mid-flight.
        "return_20d_not_surged": (
            return_20d < float(require_rule(rules, "price_position.max_return_20d_not_surged"))
        ),
        # Pre-breakout proximity: |close-EMA20|/EMA20 must be ≤ 5% (兩個方向都要近)。
        # 不只擋價格遠高於 EMA20 的「已突破」，也擋價格遠低於 EMA20 的「下跌中」。
        "close_not_far_from_ema20": (
            abs(close_distance_from_ema20) <= float(require_rule(rules, "ema.pre_breakout_close_ema20_max"))
        ),
        # EMA bunching guard: EMA5/10/20 spread ≤ 5% means the three MAs are still tightly
        # clustered. If > 5% they are already fanning out, indicating the initial move started.
        "ema_not_spread_out": (
            ema_spread <= float(require_rule(rules, "ema.pre_breakout_ema_spread_max"))
        ),
        # O'Neil Flat Base: 進場日當天突破 base 高點 + 量爆 ≥ 1.4× 50 日均量
        # 用 require_rule 讓 optimizer 可以調這 2 個 threshold:
        #   classification.breakout_pivot_buffer (default 0.001 = 0.1%)
        #   classification.breakout_volume_ratio_min (default 1.4)
        "breakout_today": (
            close_today > base_high * (1.0 + float(require_rule(rules, "classification.breakout_pivot_buffer")))
            and volume_today_shares > avg_volume_50_shares * float(require_rule(rules, "classification.breakout_volume_ratio_min"))
        ),
        # O'Neil Flat Base: base 整理深度 ≤ 15% (rule: classification.base_depth_max)
        "base_depth_ok": (
            base_range_pct <= float(require_rule(rules, "classification.base_depth_max"))
        ),
    }

    scores = CandidateScores(
        liquidity_score=_score_liquidity(avg_turnover_20, avg_volume_20_lots, rules),
        price_position_score=_score_price_position(return_60d, return_20d, return_60_to_20, return_5d, rules),
        base_compression_score=_score_base(base_range_pct, volume_contraction_ratio, return_60_to_20, rules),
        volume_score=_score_volume(volume_recovery_ratio_5d, volume_today_ratio_20, volume_contraction_ratio, rules),
        ema_convergence_score=_score_ema(
            ema_spread,
            close_today,
            ema5,
            ema10,
            ema20,
            ema5_slope,
            ema10_slope,
            ema20_slope,
            bullish_stack,
            rules,
        ),
        relative_strength_score=_score_relative_strength(relative_strength_20d, relative_strength_60d, downside_resilience_20d, rules),
    )
    risk_score = _risk_score(return_60d, return_5d, close_distance_from_ema20, upper_shadow_ratio_today, risk_flags, rules)
    surge_candidate_score = _final_score(scores, risk_score, rules)
    setup_price_position_score = _score_setup_price_position(
        return_20d,
        return_60d,
        return_90d,
        close_to_base_high_ratio,
        close_from_base_low_pct,
        close_from_ema20_pct,
        rules,
    )
    ema_micro_upturn_score = _score_ema_micro_upturn(
        ema_spread,
        close_from_ema20_pct,
        ema5,
        ema10,
        ema5_slope,
        ema10_slope,
        ema20_slope,
        rules,
    )
    volume_setup_score = _score_volume_setup(volume_recovery_ratio_5d, volume_contraction_ratio, rules)
    volume_contraction_score = _score_volume_contraction(volume_contraction_ratio, rules)
    ema_down_to_up_transition_score = _score_ema_down_to_up_transition(
        ema5_slope, ema5_slope_prev_10d,
        ema10_slope, ema10_slope_prev_10d,
        ema20_slope, ema20_slope_prev_20d,
        ema_spread, close_from_ema20_pct, rules,
    )
    pre_breakout_score = _final_pre_breakout_score(
        scores.base_compression_score,
        ema_micro_upturn_score,
        ema_down_to_up_transition_score,
        setup_price_position_score,
        volume_contraction_score,
        scores.relative_strength_score,
        scores.liquidity_score,
        risk_score,
        rules,
    )
    features_with_scores = {
        **features,
        "pre_breakout_score": pre_breakout_score,
        "ema_micro_upturn_score": ema_micro_upturn_score,
        "base_compression_score": scores.base_compression_score,
        "ema_down_to_up_transition_score": ema_down_to_up_transition_score,
    }
    entry_tier = _compute_entry_tier(features_with_scores, rules, risk_score)

    sector_info = get_sector_info(stock_id)
    metrics = CandidateMetrics(
        return_60d=round(return_60d, 4),
        return_90d=round(return_90d, 4),
        return_20d=round(return_20d, 4),
        range_90d=round(range_90d, 4),
        high_90d=round(high_90d, 2),
        low_90d=round(low_90d, 2),
        sector_category=sector_info["category"] if sector_info else None,
        sector_label=sector_info["label"] if sector_info else None,
        return_60_to_20=round(return_60_to_20, 4),
        return_5d=round(return_5d, 4),
        avg_volume_20_lots=round(avg_volume_20_lots, 2),
        avg_turnover_20=round(avg_turnover_20, 2),
        base_high=round(base_high, 2),
        base_low=round(base_low, 2),
        base_range_pct=round(base_range_pct, 4),
        volume_contraction_ratio=round(volume_contraction_ratio, 4),
        volume_recovery_ratio_5d=round(volume_recovery_ratio_5d, 4),
        volume_today_ratio_20=round(volume_today_ratio_20, 4),
        ema_spread=round(ema_spread, 4),
        ema5_slope=round(ema5_slope, 4),
        ema5_slope_prev_10d=round(ema5_slope_prev_10d, 4),
        ema10_slope_prev_10d=round(ema10_slope_prev_10d, 4),
        ema20_slope_prev_20d=round(ema20_slope_prev_20d, 4),
        ema_down_to_up_transition_score=ema_down_to_up_transition_score,
        ema10_slope=round(ema10_slope, 4),
        ema20_slope=round(ema20_slope, 4),
        relative_strength_20d=round(relative_strength_20d, 4) if relative_strength_20d is not None else None,
        relative_strength_60d=round(relative_strength_60d, 4) if relative_strength_60d is not None else None,
        downside_resilience_20d=round(downside_resilience_20d, 4) if downside_resilience_20d is not None else None,
        close_distance_from_ema20=round(close_distance_from_ema20, 4),
        close_from_ema20_pct=round(close_from_ema20_pct, 4),
        close_to_base_high_ratio=round(close_to_base_high_ratio, 4),
        close_from_base_low_pct=round(close_from_base_low_pct, 4),
        pre_breakout_score=pre_breakout_score,
        setup_price_position_score=setup_price_position_score,
        ema_micro_upturn_score=ema_micro_upturn_score,
        volume_setup_score=volume_setup_score,
        volume_contraction_score=volume_contraction_score,
        upper_shadow_ratio_today=round(upper_shadow_ratio_today, 4),
        recent_base_score=recent_base_score,
        recent_base_window_bars=recent_base_window_bars,
        recent_base_range_pct=recent_base_range_pct,
        recent_base_contraction_ratio=recent_base_contraction_ratio,
        entry_tier=entry_tier,
    )

    candidate_type = _classify_candidate(
        surge_candidate_score,
        risk_score,
        risk_flags,
        condition_gates,
        metrics,
        scores,
        bullish_stack,
        rules,
    )
    if debug_context is not None:
        debug_context.update({
            "close_today": round(close_today, 4),
            "ema5": round(ema5, 4),
            "ema10": round(ema10, 4),
            "ema20": round(ema20, 4),
            "bullish_stack": bullish_stack,
            "close_above_all_emas": close_above_all_emas,
            "ema_near_convergence": ema_near_convergence,
            "ema_micro_upturn": ema_micro_upturn,
            "condition_gates": condition_gates.copy(),
        })
    if candidate_type == "不符合" and not include_unfit:
        return None

    confidence_score = _confidence_score(missing_data, data_quality_flags, rules)
    if source_info_dict.get("is_mock_data") and candidate_type in {"起漲前觀察", "初動候選", "動能確認"}:
        candidate_type = "初動觀察" if surge_candidate_score >= int(require_rule(rules, "classification.observation_score_min")) else "不符合"
    source_info_dict.setdefault("ohlcv_source", "unavailable")
    source_info_dict.setdefault("turnover_source", "estimated" if "turnover_value_estimated" in data_quality_flags else "missing")
    source_info_dict["market_index_source"] = market_index_source
    source_info_dict.setdefault("is_mock_data", False)
    source_info_dict["bars_count"] = len(normalized)
    source_info_dict["data_warnings"] = sorted(set(source_warnings + data_quality_flags))
    return SurgeCandidateResult(
        stock_id=stock_id,
        stock_name=stock_name,
        candidate_type=candidate_type,
        surge_candidate_score=surge_candidate_score,
        confidence_score=confidence_score,
        risk_score=risk_score,
        scores=scores,
        metrics=metrics,
        reasons=_build_reasons(metrics, rules) if candidate_type != "不符合" else [],
        watch_conditions=_build_watch_conditions(metrics) if candidate_type != "不符合" else [],
        invalidation=_build_invalidation(metrics) if candidate_type != "不符合" else [],
        risk_flags=risk_flags,
        missing_data=missing_data,
        data_quality_flags=data_quality_flags,
        source_info=source_info_dict,
        extras={},
    )


def _model_to_dict(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    if hasattr(model, "dict"):
        return model.dict()
    return dict(model)


def _stock_code_from_universe_item(item: dict[str, Any]) -> str:
    return str(item.get("stock_code") or item.get("code") or item.get("stock_id") or "").strip()


def _dedupe_universe_items(universe: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    duplicate_count = 0
    for item in universe:
        stock_id = _stock_code_from_universe_item(item)
        if not stock_id:
            unique.append(item)
            continue
        if stock_id in seen:
            duplicate_count += 1
            continue
        seen.add(stock_id)
        unique.append(item)
    return unique, duplicate_count


def _dedupe_result_rows(rows: list[SurgeCandidateResult]) -> tuple[list[SurgeCandidateResult], int]:
    seen: set[str] = set()
    unique: list[SurgeCandidateResult] = []
    duplicate_count = 0
    for row in rows:
        if row.stock_id in seen:
            duplicate_count += 1
            continue
        seen.add(row.stock_id)
        unique.append(row)
    return unique, duplicate_count


def _debug_row(result: SurgeCandidateResult, debug_context: dict[str, Any]) -> dict[str, Any]:
    return {
        "stock_id": result.stock_id,
        "stock_name": result.stock_name,
        "candidate_type": result.candidate_type,
        "surge_candidate_score": result.surge_candidate_score,
        "risk_score": result.risk_score,
        "risk_flags": list(result.risk_flags),
        "missing_data": list(result.missing_data),
        "source_info": dict(result.source_info),
        "metrics": _model_to_dict(result.metrics),
        "scores": _model_to_dict(result.scores),
        "debug_context": dict(debug_context),
    }


def _pass_rate(pass_count: int, fail_count: int) -> float:
    total = pass_count + fail_count
    return round(pass_count / total, 4) if total else 0.0


def _debug_example(
    row: dict[str, Any],
    *,
    key_metrics: dict[str, Any],
    threshold: Any,
    distance: float,
) -> dict[str, Any]:
    return {
        "stock_id": row["stock_id"],
        "stock_name": row["stock_name"],
        "key_metrics": key_metrics,
        "threshold": threshold,
        "distance_to_pass": round(float(distance), 6),
    }


def _debug_condition(
    name: str,
    rows: list[dict[str, Any]],
    checker: Callable[[dict[str, Any]], tuple[bool, dict[str, Any], Any, float]],
) -> dict[str, Any]:
    failed: list[dict[str, Any]] = []
    pass_count = 0
    for row in rows:
        passed, key_metrics, threshold, distance = checker(row)
        if passed:
            pass_count += 1
        else:
            failed.append(_debug_example(row, key_metrics=key_metrics, threshold=threshold, distance=distance))
    failed.sort(key=lambda item: item["distance_to_pass"])
    fail_count = len(failed)
    return {
        "condition": name,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "pass_rate": _pass_rate(pass_count, fail_count),
        "top_10_closest_failed_examples": failed[:10],
    }


def _ema_debug_summary(rows: list[dict[str, Any]], rules: dict[str, Any]) -> dict[str, Any]:
    tight_spread = float(require_rule(rules, "ema.tight_spread"))
    medium_spread = float(require_rule(rules, "ema.medium_spread"))
    initial_move_spread = float(require_rule(rules, "ema.initial_move_spread"))
    extended_spread = float(require_rule(rules, "ema.extended_spread"))
    ema5_micro_upturn_min = float(require_rule(rules, "ema.ema5_micro_upturn_min"))
    ema10_flat_floor = float(require_rule(rules, "ema.ema10_flat_floor"))
    ema20_flat_floor = float(require_rule(rules, "ema.ema20_flat_floor"))

    spread_distribution = {
        "lt_3pct": 0,
        "3pct_to_5pct": 0,
        "5pct_to_8pct": 0,
        "8pct_to_12pct": 0,
        "gte_12pct": 0,
    }
    ema5_micro_upturn_count = 0
    ema10_flat_or_up_count = 0
    ema20_not_meaningfully_down_count = 0
    ema_near_convergence_count = 0
    ema_micro_upturn_count = 0
    ema_full_bullish_alignment_count = 0

    for row in rows:
        metrics = row["metrics"]
        debug_context = row.get("debug_context", {})
        ema_spread = float(metrics["ema_spread"])
        ema5_slope = float(metrics["ema5_slope"])
        ema10_slope = float(metrics["ema10_slope"])
        ema20_slope = float(metrics["ema20_slope"])

        if ema_spread < tight_spread:
            spread_distribution["lt_3pct"] += 1
        elif ema_spread < medium_spread:
            spread_distribution["3pct_to_5pct"] += 1
        elif ema_spread < initial_move_spread:
            spread_distribution["5pct_to_8pct"] += 1
        elif ema_spread < extended_spread:
            spread_distribution["8pct_to_12pct"] += 1
        else:
            spread_distribution["gte_12pct"] += 1

        if ema_spread < initial_move_spread:
            ema_near_convergence_count += 1
        ema5_ok = ema5_slope > ema5_micro_upturn_min
        ema10_ok = ema10_slope > ema10_flat_floor
        ema20_ok = ema20_slope > ema20_flat_floor
        if ema5_ok:
            ema5_micro_upturn_count += 1
        if ema10_ok:
            ema10_flat_or_up_count += 1
        if ema20_ok:
            ema20_not_meaningfully_down_count += 1
        if ema5_ok and ema10_ok and ema20_ok:
            ema_micro_upturn_count += 1
        if bool(debug_context.get("bullish_stack")):
            ema_full_bullish_alignment_count += 1

    return {
        "ema_spread_distribution": spread_distribution,
        "ema_slope_distribution": {
            "ema5_slope_5d": {
                "micro_upturn_count": ema5_micro_upturn_count,
                "not_micro_upturn_count": len(rows) - ema5_micro_upturn_count,
                "threshold_min_exclusive": ema5_micro_upturn_min,
            },
            "ema10_slope_5d": {
                "flat_or_micro_upturn_count": ema10_flat_or_up_count,
                "meaningfully_down_count": len(rows) - ema10_flat_or_up_count,
                "threshold_min_exclusive": ema10_flat_floor,
            },
            "ema20_slope_10d": {
                "not_meaningfully_down_count": ema20_not_meaningfully_down_count,
                "meaningfully_down_count": len(rows) - ema20_not_meaningfully_down_count,
                "threshold_min_exclusive": ema20_flat_floor,
            },
        },
        "ema_near_convergence_count": ema_near_convergence_count,
        "ema_micro_upturn_count": ema_micro_upturn_count,
        "ema_full_bullish_alignment_count": ema_full_bullish_alignment_count,
    }


def _range_distribution(values: list[Optional[float]], buckets: list[tuple[str, Optional[float], Optional[float]]]) -> dict[str, int]:
    distribution = {label: 0 for label, _lower, _upper in buckets}
    for raw_value in values:
        if raw_value is None:
            distribution["missing"] = distribution.get("missing", 0) + 1
            continue
        value = float(raw_value)
        for label, lower, upper in buckets:
            lower_ok = lower is None or value >= lower
            upper_ok = upper is None or value < upper
            if lower_ok and upper_ok:
                distribution[label] += 1
                break
    return distribution


def _debug_distributions(rows: list[dict[str, Any]], rules: dict[str, Any]) -> dict[str, Any]:
    metrics_rows = [row["metrics"] for row in rows]
    scores = [int(row["surge_candidate_score"]) for row in rows]
    return {
        "volume_contraction_distribution": _range_distribution(
            [float(metrics["volume_contraction_ratio"]) for metrics in metrics_rows],
            [
                ("lt_0_8", None, float(require_rule(rules, "base.contraction_ratio"))),
                ("0_8_to_1_0", float(require_rule(rules, "base.contraction_ratio")), float(require_rule(rules, "base.neutral_contraction_ratio"))),
                ("1_0_to_1_2", float(require_rule(rules, "base.neutral_contraction_ratio")), float(require_rule(rules, "base.expansion_ratio"))),
                ("gte_1_2", float(require_rule(rules, "base.expansion_ratio")), None),
            ],
        ),
        "volume_recovery_distribution": _range_distribution(
            [float(metrics["volume_recovery_ratio_5d"]) for metrics in metrics_rows],
            [
                ("lt_0_9", None, float(require_rule(rules, "volume.weak_recovery_ratio"))),
                ("0_9_to_1_05", float(require_rule(rules, "volume.weak_recovery_ratio")), float(require_rule(rules, "volume.mild_recovery_ratio"))),
                ("1_05_to_1_2", float(require_rule(rules, "volume.mild_recovery_ratio")), float(require_rule(rules, "volume.sustained_recovery_ratio"))),
                ("1_2_to_1_5", float(require_rule(rules, "volume.sustained_recovery_ratio")), float(require_rule(rules, "volume.strong_recovery_ratio"))),
                ("gte_1_5", float(require_rule(rules, "volume.strong_recovery_ratio")), None),
            ],
        ),
        "relative_strength_distribution": {
            "rs20": _range_distribution(
                [metrics["relative_strength_20d"] for metrics in metrics_rows],
                [("lt_0", None, 0.0), ("gte_0", 0.0, None)],
            ),
            "rs60": _range_distribution(
                [metrics["relative_strength_60d"] for metrics in metrics_rows],
                [("lt_0", None, 0.0), ("gte_0", 0.0, None)],
            ),
        },
        "score_distribution": _range_distribution(
            [float(score) for score in scores],
            [
                ("lt_55", None, 55.0),
                ("55_to_60", 55.0, 60.0),
                ("60_to_65", 60.0, 65.0),
                ("65_to_70", 65.0, 70.0),
                ("gte_70", 70.0, None),
            ],
        ),
        "pre_breakout_score_distribution": _range_distribution(
            [float(metrics.get("pre_breakout_score", 0)) for metrics in metrics_rows],
            [("lt_50", None, 50.0), ("50_to_60", 50.0, 60.0), ("60_to_70", 60.0, 70.0), ("gte_70", 70.0, None)],
        ),
        "setup_price_position_score_distribution": _range_distribution(
            [float(metrics.get("setup_price_position_score", 0)) for metrics in metrics_rows],
            [("lt_50", None, 50.0), ("50_to_70", 50.0, 70.0), ("gte_70", 70.0, None)],
        ),
        "ema_micro_upturn_score_distribution": _range_distribution(
            [float(metrics.get("ema_micro_upturn_score", 0)) for metrics in metrics_rows],
            [("lt_50", None, 50.0), ("50_to_70", 50.0, 70.0), ("gte_70", 70.0, None)],
        ),
        "close_from_ema20_distribution": _range_distribution(
            [float(metrics.get("close_from_ema20_pct", metrics.get("close_distance_from_ema20", 0))) for metrics in metrics_rows],
            [("lt_minus_8pct", None, -0.08), ("minus_8pct_to_8pct", -0.08, 0.08), ("8pct_to_12pct", 0.08, 0.12), ("12pct_to_15pct", 0.12, 0.15), ("gte_15pct", 0.15, None)],
        ),
        "close_to_base_high_distribution": _range_distribution(
            [float(metrics.get("close_to_base_high_ratio", 0)) for metrics in metrics_rows],
            [("lt_0_95", None, 0.95), ("0_95_to_1_03", 0.95, 1.03), ("1_03_to_1_08", 1.03, 1.08), ("gte_1_08", 1.08, None)],
        ),
        "return_20d_distribution": _range_distribution(
            [float(metrics["return_20d"]) for metrics in metrics_rows],
            [("lt_8pct", None, 0.08), ("8pct_to_12pct", 0.08, 0.12), ("12pct_to_15pct", 0.12, 0.15), ("gte_15pct", 0.15, None)],
        ),
        "return_90d_distribution": _range_distribution(
            [metrics.get("return_90d") for metrics in metrics_rows],
            [("lt_0", None, 0.0), ("0_to_10pct", 0.0, 0.10), ("10pct_to_20pct", 0.10, 0.20), ("20pct_to_35pct", 0.20, 0.35), ("gte_35pct", 0.35, None)],
        ),
    }


def _condition_checkers(parameters: ScreenerParameters, rules: dict[str, Any]) -> dict[str, Callable[[dict[str, Any]], tuple[bool, dict[str, Any], Any, float]]]:
    min_return_60d = parameters.min_return_60d
    max_return_60d = parameters.max_return_60d
    max_base_return = parameters.max_base_return
    min_return_20d = parameters.min_return_20d
    min_avg_volume_lots = parameters.min_avg_volume_lots
    min_avg_turnover = parameters.min_avg_turnover
    max_base_range = float(require_rule(rules, "base.loose_range_pct"))
    max_volume_contraction = float(require_rule(rules, "base.expansion_ratio"))
    min_volume_recovery_5d = float(require_rule(rules, "volume.mild_recovery_ratio"))
    min_volume_today_ratio = float(require_rule(rules, "volume.single_day_surge_ratio"))
    max_ema_spread = float(require_rule(rules, "ema.extended_spread"))
    ema5_micro_upturn_min = float(require_rule(rules, "ema.ema5_micro_upturn_min"))
    ema10_flat_floor = float(require_rule(rules, "ema.ema10_flat_floor"))
    ema20_flat_floor = float(require_rule(rules, "ema.ema20_flat_floor"))
    max_return_5d = float(require_rule(rules, "price_position.parabolic_return_5d"))
    max_risk_score = int(require_rule(rules, "classification.overheat_risk_score"))
    risk_blocking_flags = {
        "parabolic_rise_5d",
        "high_upper_shadow_with_volume",
        "volume_climax",
        "extended_from_ema20",
        "low_liquidity",
    }

    def metrics(row: dict[str, Any]) -> dict[str, Any]:
        return row["metrics"]

    def liquidity(row: dict[str, Any]) -> tuple[bool, dict[str, Any], Any, float]:
        m = metrics(row)
        volume = float(m["avg_volume_20_lots"])
        turnover = float(m["avg_turnover_20"])
        passed = volume >= min_avg_volume_lots or turnover >= min_avg_turnover
        volume_gap = max(0.0, (min_avg_volume_lots - volume) / min_avg_volume_lots)
        turnover_gap = max(0.0, (min_avg_turnover - turnover) / min_avg_turnover)
        return passed, {
            "avg_volume_20_lots": volume,
            "avg_turnover_20": turnover,
        }, {
            "avg_volume_20_lots_min": min_avg_volume_lots,
            "avg_turnover_20_min": min_avg_turnover,
            "operator": "OR",
        }, min(volume_gap, turnover_gap)

    def return_60d_range(row: dict[str, Any]) -> tuple[bool, dict[str, Any], Any, float]:
        value = float(metrics(row)["return_60d"])
        if value < min_return_60d:
            distance = min_return_60d - value
        elif value > max_return_60d:
            distance = value - max_return_60d
        else:
            distance = 0.0
        return min_return_60d <= value <= max_return_60d, {"return_60d": value}, {
            "min": min_return_60d,
            "max": max_return_60d,
        }, distance

    def return_60_to_20(row: dict[str, Any]) -> tuple[bool, dict[str, Any], Any, float]:
        value = float(metrics(row)["return_60_to_20"])
        distance = max(0.0, abs(value) - max_base_return)
        return abs(value) <= max_base_return, {"return_60_to_20": value}, {
            "absolute_max": max_base_return,
        }, distance

    def return_20d(row: dict[str, Any]) -> tuple[bool, dict[str, Any], Any, float]:
        value = float(metrics(row)["return_20d"])
        threshold = float(require_rule(rules, "price_position.medium_return_20d"))
        return value >= threshold, {"return_20d": value}, {"min": threshold}, max(0.0, threshold - value)

    def return_5d_not_overheat(row: dict[str, Any]) -> tuple[bool, dict[str, Any], Any, float]:
        value = float(metrics(row)["return_5d"])
        return value < max_return_5d, {"return_5d": value}, {"max_exclusive": max_return_5d}, max(0.0, value - max_return_5d)

    def base_range(row: dict[str, Any]) -> tuple[bool, dict[str, Any], Any, float]:
        value = float(metrics(row)["base_range_pct"])
        return value < max_base_range, {"base_range_pct": value}, {"max_exclusive": max_base_range}, max(0.0, value - max_base_range)

    def volume_contraction(row: dict[str, Any]) -> tuple[bool, dict[str, Any], Any, float]:
        value = float(metrics(row)["volume_contraction_ratio"])
        return value < max_volume_contraction, {"volume_contraction_ratio": value}, {"max_exclusive": max_volume_contraction}, max(0.0, value - max_volume_contraction)

    def volume_recovery(row: dict[str, Any]) -> tuple[bool, dict[str, Any], Any, float]:
        m = metrics(row)
        recovery_5d = float(m["volume_recovery_ratio_5d"])
        today_ratio = float(m["volume_today_ratio_20"])
        passed = recovery_5d > min_volume_recovery_5d or today_ratio > min_volume_today_ratio
        recovery_gap = max(0.0, min_volume_recovery_5d - recovery_5d)
        today_gap = max(0.0, min_volume_today_ratio - today_ratio)
        return passed, {
            "volume_recovery_ratio_5d": recovery_5d,
            "volume_today_ratio_20": today_ratio,
        }, {
            "volume_recovery_ratio_5d_min_exclusive": min_volume_recovery_5d,
            "volume_today_ratio_20_min_exclusive": min_volume_today_ratio,
            "operator": "OR",
        }, min(recovery_gap, today_gap)

    def ema_spread(row: dict[str, Any]) -> tuple[bool, dict[str, Any], Any, float]:
        value = float(metrics(row)["ema_spread"])
        return value < max_ema_spread, {"ema_spread": value}, {"max_exclusive": max_ema_spread}, max(0.0, value - max_ema_spread)

    def ema_structure(row: dict[str, Any]) -> tuple[bool, dict[str, Any], Any, float]:
        m = metrics(row)
        ctx = row["debug_context"]
        close = float(ctx.get("close_today") or 0.0)
        ema5 = float(ctx.get("ema5") or 0.0)
        ema10 = float(ctx.get("ema10") or 0.0)
        ema20 = float(ctx.get("ema20") or 0.0)
        ema5_slope = float(m["ema5_slope"])
        ema10_slope = float(m["ema10_slope"])
        ema20_slope = float(m["ema20_slope"])
        passed = (
            ema5_slope > ema5_micro_upturn_min
            and ema10_slope > ema10_flat_floor
            and ema20_slope > ema20_flat_floor
        )
        distance = (
            max(0.0, ema5_micro_upturn_min - ema5_slope)
            + max(0.0, ema10_flat_floor - ema10_slope)
            + max(0.0, ema20_flat_floor - ema20_slope)
        )
        return passed, {
            "close": close,
            "ema5": ema5,
            "ema10": ema10,
            "ema20": ema20,
            "ema5_slope": ema5_slope,
            "ema10_slope": ema10_slope,
            "ema20_slope": ema20_slope,
            "close_above_all_emas": close >= ema5 and close >= ema10 and close >= ema20,
            "ema5_gt_ema10": ema5 > ema10,
            "ema10_gt_ema20": ema10 > ema20,
        }, {
            "ema5_slope_min_exclusive": ema5_micro_upturn_min,
            "ema10_slope_min_exclusive": ema10_flat_floor,
            "ema20_slope_min_exclusive": ema20_flat_floor,
            "meaning": "micro-upturn, not full bullish alignment",
        }, distance

    def relative_strength_20d(row: dict[str, Any]) -> tuple[bool, dict[str, Any], Any, float]:
        value = metrics(row)["relative_strength_20d"]
        missing_is_neutral = "market_index" in row["missing_data"]
        passed = missing_is_neutral or (value is not None and float(value) > 0)
        distance = 0.0 if missing_is_neutral or value is None else max(0.0, -float(value))
        return passed, {"relative_strength_20d": value}, {
            "min_exclusive": 0,
            "market_index_missing_treated_as_neutral": True,
        }, distance

    def relative_strength_60d(row: dict[str, Any]) -> tuple[bool, dict[str, Any], Any, float]:
        value = metrics(row)["relative_strength_60d"]
        missing_is_neutral = "market_index" in row["missing_data"]
        passed = missing_is_neutral or (value is not None and float(value) > 0)
        distance = 0.0 if missing_is_neutral or value is None else max(0.0, -float(value))
        return passed, {"relative_strength_60d": value}, {
            "min_exclusive": 0,
            "market_index_missing_treated_as_neutral": True,
        }, distance

    def risk_filter(row: dict[str, Any]) -> tuple[bool, dict[str, Any], Any, float]:
        flags = set(row["risk_flags"])
        risk_score = int(row["risk_score"])
        blocking = sorted(flags & risk_blocking_flags)
        passed = risk_score < max_risk_score and not blocking
        distance = max(0.0, risk_score - max_risk_score) / 100 + float(len(blocking))
        return passed, {
            "risk_score": risk_score,
            "risk_flags": sorted(flags),
            "return_5d": metrics(row)["return_5d"],
            "close_distance_from_ema20": metrics(row)["close_distance_from_ema20"],
            "upper_shadow_ratio_today": metrics(row)["upper_shadow_ratio_today"],
        }, {
            "risk_score_max_exclusive": max_risk_score,
            "blocking_flags": sorted(risk_blocking_flags),
        }, distance

    def return_90d_range_checker(row: dict[str, Any]) -> tuple[bool, dict[str, Any], Any, float]:
        value = metrics(row).get("return_90d")
        if value is None:
            return True, {"return_90d": None}, {"note": "missing_treated_as_neutral"}, 0.0
        value = float(value)
        min_r = float(require_rule(rules, "price_position.min_return_90d_broad"))
        max_r = float(require_rule(rules, "price_position.max_return_90d_broad"))
        if value < min_r:
            distance = min_r - value
        elif value > max_r:
            distance = value - max_r
        else:
            distance = 0.0
        return min_r <= value <= max_r, {"return_90d": value}, {"min": min_r, "max": max_r, "filter": "broad"}, distance

    def return_90d_ideal_range_checker(row: dict[str, Any]) -> tuple[bool, dict[str, Any], Any, float]:
        value = metrics(row).get("return_90d")
        if value is None:
            return True, {"return_90d": None}, {"note": "missing_treated_as_neutral"}, 0.0
        value = float(value)
        min_r = float(require_rule(rules, "price_position.min_return_90d"))
        max_r = float(require_rule(rules, "price_position.max_return_90d"))
        if value < min_r:
            distance = min_r - value
        elif value > max_r:
            distance = value - max_r
        else:
            distance = 0.0
        return min_r <= value <= max_r, {"return_90d": value}, {"min": min_r, "max": max_r, "filter": "ideal"}, distance

    def volume_not_dried_up_checker(row: dict[str, Any]) -> tuple[bool, dict[str, Any], Any, float]:
        volume_lots = float(metrics(row)["avg_volume_20_lots"])
        min_lots = float(require_rule(rules, "liquidity.min_avg_volume_20_lots"))
        passed = volume_lots >= min_lots
        distance = max(0.0, min_lots - volume_lots)
        return passed, {"avg_volume_20_lots": volume_lots}, {"min": min_lots, "note": "liquidity_guard_not_contraction_signal"}, distance

    def return_20d_pre_breakout_checker(row: dict[str, Any]) -> tuple[bool, dict[str, Any], Any, float]:
        value = float(metrics(row)["return_20d"])
        threshold = float(require_rule(rules, "price_position.pre_breakout_return_20d_max"))
        passed = value < threshold
        distance = max(0.0, value - threshold)
        return passed, {"return_20d": value}, {"max_exclusive": threshold, "diagnostic_only": True}, distance

    def return_20d_not_surged_checker(row: dict[str, Any]) -> tuple[bool, dict[str, Any], Any, float]:
        value = float(metrics(row)["return_20d"])
        threshold = float(require_rule(rules, "price_position.max_return_20d_not_surged"))
        passed = value < threshold
        distance = max(0.0, value - threshold)
        return passed, {"return_20d": value}, {"max_exclusive": threshold}, distance

    def close_not_far_from_ema20_checker(row: dict[str, Any]) -> tuple[bool, dict[str, Any], Any, float]:
        value = float(metrics(row)["close_distance_from_ema20"])
        threshold = float(require_rule(rules, "ema.pre_breakout_close_ema20_max"))
        passed = value <= threshold
        distance = max(0.0, value - threshold)
        return passed, {"close_distance_from_ema20": value}, {"max_inclusive": threshold}, distance

    def ema_not_spread_out_checker(row: dict[str, Any]) -> tuple[bool, dict[str, Any], Any, float]:
        value = float(metrics(row)["ema_spread"])
        threshold = float(require_rule(rules, "ema.pre_breakout_ema_spread_max"))
        passed = value <= threshold
        distance = max(0.0, value - threshold)
        return passed, {"ema_spread": value}, {"max_inclusive": threshold}, distance

    return {
        "liquidity": liquidity,
        "return_60d_range": return_60d_range,
        "return_60_to_20": return_60_to_20,
        "return_20d": return_20d,
        "return_5d_not_overheat": return_5d_not_overheat,
        "base_range": base_range,
        "volume_contraction": volume_contraction,
        "volume_recovery": volume_recovery,
        "ema_spread": ema_spread,
        "ema_structure": ema_structure,
        "relative_strength_20d": relative_strength_20d,
        "relative_strength_60d": relative_strength_60d,
        "risk_filter": risk_filter,
        "return_90d_range": return_90d_range_checker,
        "return_90d_ideal_range": return_90d_ideal_range_checker,
        "volume_not_dried_up": volume_not_dried_up_checker,
        "return_20d_pre_breakout": return_20d_pre_breakout_checker,
        "return_20d_not_surged": return_20d_not_surged_checker,
        "close_not_far_from_ema20": close_not_far_from_ema20_checker,
        "ema_not_spread_out": ema_not_spread_out_checker,
    }


def _build_funnel_report(
    *,
    universe_size: int,
    ohlcv_failures: list[dict[str, Any]],
    evaluated_rows: list[dict[str, Any]],
    parameters: ScreenerParameters,
    rules: dict[str, Any],
    data_source_report: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    checkers = _condition_checkers(parameters, rules)
    ohlcv_pass_count = len(evaluated_rows)
    ohlcv_failed = sorted(
        [
            {
                "stock_id": item["stock_id"],
                "stock_name": item["stock_name"],
                "key_metrics": {"bars_available": item["bars_available"]},
                "threshold": {"minimum_bars": int(require_rule(rules, "history.minimum_days"))},
                "distance_to_pass": max(0, int(require_rule(rules, "history.minimum_days")) - item["bars_available"]),
            }
            for item in ohlcv_failures
        ],
        key=lambda item: item["distance_to_pass"],
    )
    condition_reports = {
        "ohlcv_sufficient": {
            "condition": "ohlcv_sufficient",
            "pass_count": ohlcv_pass_count,
            "fail_count": len(ohlcv_failures),
            "pass_rate": _pass_rate(ohlcv_pass_count, len(ohlcv_failures)),
            "top_10_closest_failed_examples": ohlcv_failed[:10],
        }
    }
    for name, checker in checkers.items():
        condition_reports[name] = _debug_condition(name, evaluated_rows, checker)
    if "return_20d_pre_breakout" in condition_reports:
        condition_reports["return_20d_pre_breakout"]["diagnostic_only"] = True

    stage_counts: dict[str, int] = {
        "universe_size": universe_size,
        "ohlcv_sufficient_count": ohlcv_pass_count,
    }
    stage_sequence = [
        ("liquidity_pass_count", "liquidity"),
        ("return_60d_range_pass_count", "return_60d_range"),              # 2-month return range gate
        ("return_90d_range_pass_count", "return_90d_range"),              # 3-month broad hard filter [0%, 35%]
        ("return_90d_ideal_range_pass_count", "return_90d_ideal_range"),  # 3-month ideal zone [10%, 30%] — observation only
        ("volume_not_dried_up_pass_count", "volume_not_dried_up"),
        ("return_20d_not_surged_pass_count", "return_20d_not_surged"),
        ("close_not_far_from_ema20_pass_count", "close_not_far_from_ema20"),
        ("ema_not_spread_out_pass_count", "ema_not_spread_out"),
        ("return_5d_not_overheat_count", "return_5d_not_overheat"),
        ("score_gte_55_count", "score_gte_55"),
        ("score_gte_60_count", "score_gte_60"),
        ("risk_filter_pass_count", "risk_filter"),
    ]
    sequential_checkers = dict(checkers)
    sequential_checkers["score_gte_55"] = lambda row: (
        int(row["surge_candidate_score"]) >= int(require_rule(rules, "classification.disqualify_score_below")),
        {"surge_candidate_score": int(row["surge_candidate_score"])},
        {"min": int(require_rule(rules, "classification.disqualify_score_below"))},
        max(0.0, int(require_rule(rules, "classification.disqualify_score_below")) - int(row["surge_candidate_score"])) / 100,
    )
    sequential_checkers["score_gte_60"] = lambda row: (
        int(row["surge_candidate_score"]) >= int(require_rule(rules, "classification.observation_score_min")),
        {"surge_candidate_score": int(row["surge_candidate_score"])},
        {"min": int(require_rule(rules, "classification.observation_score_min"))},
        max(0.0, int(require_rule(rules, "classification.observation_score_min")) - int(row["surge_candidate_score"])) / 100,
    )
    remaining = list(evaluated_rows)
    for stage_name, condition_name in stage_sequence:
        checker = sequential_checkers[condition_name]
        remaining = [row for row in remaining if checker(row)[0]]
        stage_counts[stage_name] = len(remaining)

    final_matched_count = sum(1 for row in evaluated_rows if row["candidate_type"] != "不符合")
    stage_counts["final_matched_count"] = final_matched_count
    ema_summary = _ema_debug_summary(evaluated_rows, rules)
    distributions = _debug_distributions(evaluated_rows, rules)
    stage_counts["ema_near_convergence_count"] = ema_summary["ema_near_convergence_count"]
    stage_counts["ema_micro_upturn_count"] = ema_summary["ema_micro_upturn_count"]
    stage_counts["ema_full_bullish_alignment_count"] = ema_summary["ema_full_bullish_alignment_count"]
    sequential_funnel = {
        "stages": stage_counts,
        "order": [stage for stage, _condition in stage_sequence],
        "description": "Sequential funnel now contains only relaxed hard filters plus score/risk checkpoints.",
    }
    return {
        "stage_counts": stage_counts,
        "condition_reports": condition_reports,
        "sequential_funnel": sequential_funnel,
        "independent_condition_counts": condition_reports,
        "data_source_report": data_source_report or {},
        "ema_spread_distribution": ema_summary["ema_spread_distribution"],
        "ema_slope_distribution": ema_summary["ema_slope_distribution"],
        "ema_near_convergence_count": ema_summary["ema_near_convergence_count"],
        "ema_micro_upturn_count": ema_summary["ema_micro_upturn_count"],
        "ema_full_bullish_alignment_count": ema_summary["ema_full_bullish_alignment_count"],
        **distributions,
        "notes": [
            "Debug funnel is observational only; soft signals contribute to scores instead of acting as hard filters.",
            "Sequential funnel contains relaxed hard filters and score checkpoints; independent condition counts are computed across OHLCV-sufficient stocks.",
            "Relative strength treats missing market index as neutral to match Phase 1 graceful degradation.",
        ],
    }


def _default_universe_report(source: str = "unavailable") -> dict[str, Any]:
    return {
        "source": source,
        "twse_count": 0,
        "tpex_count": 0,
        "finmind_count": 0,
        "mock_count": 0,
        "stock_count": 0,
        "fallback_used": False,
        "warnings": [],
    }


def _empty_data_source_report(universe_report: Optional[dict[str, Any]], market_index_report: Optional[dict[str, Any]]) -> dict[str, Any]:
    rate_limit_state = get_finmind_rate_limit_state()
    return {
        "mode": data_source_settings.effective_data_mode(),
        "universe": universe_report or _default_universe_report(),
        "ohlcv": {
            "finmind_count": 0,
            "twse_official_count": 0,
            "tpex_official_count": 0,
            "yfinance_count": 0,
            "mock_count": 0,
            "insufficient_data_count": 0,
            "error_count": 0,
            "finmind_rate_limited": bool(rate_limit_state["finmind_rate_limited"]),
            "finmind_disabled_until": rate_limit_state["finmind_disabled_until"],
        },
        "market_index": market_index_report or {
            "source": "unavailable",
            "available": False,
            "fallback_used": True,
            "warnings": ["market_index_unavailable"],
        },
        "turnover": {
            "official_turnover_count": 0,
            "finmind_trading_money_count": 0,
            "estimated_turnover_count": 0,
            "missing_turnover_count": 0,
        },
        "warnings": [],
    }


def _count_source_info(report: dict[str, Any], source_info: dict[str, Any], *, official_patch: bool = False) -> None:
    source = str(source_info.get("ohlcv_source") or "unavailable")
    turnover_source = str(source_info.get("turnover_source") or "missing")
    if source == "finmind":
        report["ohlcv"]["finmind_count"] += 1
    elif source == "yfinance":
        report["ohlcv"]["yfinance_count"] += 1
    elif source == "mock":
        report["ohlcv"]["mock_count"] += 1
    elif source == "twse_official":
        report["ohlcv"]["twse_official_count"] += 1
    elif source == "unavailable":
        report["ohlcv"]["insufficient_data_count"] += 1
    if official_patch:
        report["ohlcv"]["tpex_official_count"] += 1

    if turnover_source == "official":
        report["turnover"]["official_turnover_count"] += 1
    elif turnover_source == "finmind_trading_money":
        report["turnover"]["finmind_trading_money_count"] += 1
    elif turnover_source == "estimated":
        report["turnover"]["estimated_turnover_count"] += 1
    else:
        report["turnover"]["missing_turnover_count"] += 1


async def scan_surge_candidates(
    parameters: ScreenerParameters,
    *,
    df_market: Optional[pd.DataFrame] = None,
    universe: Optional[list[dict[str, Any]]] = None,
    data_warnings: Optional[list[str]] = None,
    progress_callback: Optional[ProgressCallback] = None,
    debug: bool = False,
    market_index_report: Optional[dict[str, Any]] = None,
) -> ScreenerResponse:
    rules = load_surge_candidate_rules()
    warnings = list(data_warnings or [])
    if parameters.market != "TW":
        raise ValueError("Only market=TW is supported in Phase 1.")

    if universe is None:
        stock_payload = await get_tw_stocks(limit=parameters.scan_limit)
        universe = stock_payload.get("stocks", [])
        data_source = stock_payload.get("data_source", "unknown")
        universe_total = int(stock_payload.get("total") or len(universe))
        universe_report = stock_payload.get("source_report") or _default_universe_report(data_source)
    else:
        data_source = "test"
        universe = universe[: parameters.scan_limit]
        universe_total = len(universe)
        universe_report = {
            **_default_universe_report("test"),
            "stock_count": len(universe),
        }

    universe, duplicate_universe_count = _dedupe_universe_items(universe)

    if not universe:
        raise UniverseLoadError("Taiwan stock universe is empty.")

    universe_size_estimated = data_source not in {"live", "public"} or not (1500 <= universe_total <= 2200)
    if universe_size_estimated and "universe_size_estimated" not in warnings:
        warnings.append("universe_size_estimated")
    if df_market is None and "market_index_unavailable" not in warnings:
        warnings.append("market_index_unavailable")

    data_source_report = _empty_data_source_report(universe_report, market_index_report)
    if duplicate_universe_count:
        data_source_report["universe"]["duplicate_removed_count"] = duplicate_universe_count
        data_source_report["warnings"].append("duplicate_universe_entries_deduped")

    tpex_quote_map: dict[str, dict[str, Any]] = {}
    if data_source_settings.prefer_official_sources():
        try:
            tpex_quote_map = await fetch_tpex_mainboard_quote_map()
        except Exception:
            data_source_report["warnings"].append("tpex_official_quotes_unavailable")

    summary = {"起漲前觀察": 0, "初動觀察": 0, "初動候選": 0, "動能確認": 0, "偏熱觀察": 0, "不符合": 0}
    rows: list[SurgeCandidateResult] = []
    debug_rows: list[dict[str, Any]] = []
    debug_ohlcv_failures: list[dict[str, Any]] = []
    total = len(universe)
    _report_progress(progress_callback, {
        "stage": "scanning",
        "processed": 0,
        "total": total,
        "message": f"取得股票清單完成，準備掃描 {total} 檔",
    })

    for index, item in enumerate(universe, start=1):
        stock_id = str(item.get("stock_code") or item.get("code") or "").strip()
        if not stock_id:
            _report_progress(progress_callback, {
                "stage": "scanning",
                "processed": index,
                "total": total,
                "message": "略過缺少代號的股票",
            })
            continue
        stock_name = str(item.get("company_name") or item.get("name") or stock_id)
        try:
            _report_progress(progress_callback, {
                "stage": "scanning",
                "processed": index - 1,
                "total": total,
                "current_stock_id": stock_id,
                "current_stock_name": stock_name,
                "message": f"正在掃描 {stock_id} {stock_name}",
            })
            load_result = await get_tw_price_history_with_source(stock_id, 150)
            official_patch = False
            source_info = load_result.source_info
            if stock_id in tpex_quote_map:
                load_result.candles, source_info, official_patch = _apply_official_latest_quote(
                    load_result.candles,
                    tpex_quote_map.get(stock_id),
                    load_result.source_info,
                )
            source_info.market_index_source = (market_index_report or {}).get("source", "unavailable")
            _count_source_info(data_source_report, source_info.to_dict(), official_patch=official_patch)
            if load_result.error or len(load_result.candles) < int(require_rule(rules, "history.minimum_days")):
                if debug:
                    debug_ohlcv_failures.append({
                        "stock_id": stock_id,
                        "stock_name": stock_name,
                        "bars_available": len(load_result.candles),
                    })
                continue
            df = candles_to_dataframe(load_result.candles)
            debug_context: dict[str, Any] = {}
            result = evaluate_surge_candidate(
                stock_id,
                stock_name,
                df,
                df_market,
                parameters=parameters,
                include_unfit=True,
                universe_size_estimated=universe_size_estimated,
                debug_context=debug_context if debug else None,
                source_info=source_info.to_dict(),
                market_index_source=source_info.market_index_source,
            )
            if result is None:
                if debug:
                    debug_ohlcv_failures.append({
                        "stock_id": stock_id,
                        "stock_name": stock_name,
                        "bars_available": len(df),
                    })
                continue
            if parameters.include_canslim:
                as_of_date = str(df["date"].iloc[-1])[:10] if "date" in df and not df.empty else datetime.now(TW_TIMEZONE).strftime("%Y-%m-%d")
                _attach_canslim_observation(result, stock_id, df, as_of_date)
            if debug:
                debug_rows.append(_debug_row(result, debug_context))
            summary[result.candidate_type] = summary.get(result.candidate_type, 0) + 1
            if parameters.include_unfit or (
                result.candidate_type != "不符合"
                and result.surge_candidate_score >= int(require_rule(rules, "classification.observation_score_min"))
            ):
                rows.append(result)
        except ScanCancelled:
            raise
        except Exception as exc:
            data_source_report["ohlcv"]["error_count"] += 1
            logger.warning("Screener skipped %s: %s", stock_id, exc)
            continue
        finally:
            _report_progress(progress_callback, {
                "stage": "scanning",
                "processed": index,
                "total": total,
                "current_stock_id": stock_id,
                "current_stock_name": stock_name,
                "message": f"已掃描 {index}/{total} 檔",
            })

    if parameters.candidate_type:
        rows = [row for row in rows if row.candidate_type == parameters.candidate_type]

    # AI 科技股 sector filter (6-Layer Framework)
    if parameters.ai_tech_only:
        ai_codes = list_ai_tech_codes()
        rows = [row for row in rows if row.stock_id in ai_codes]

    # 分類優先排序 — 起漲前觀察 永遠排最前面，避免高分的偏熱觀察把它們擠出 limit 範圍。
    # 同分類內再按使用者選的 sort_by 排序。
    category_priority = {
        "起漲前觀察": 5,
        "初動候選": 4,
        "初動觀察": 3,
        "動能確認": 2,
        "偏熱觀察": 1,
        "不符合": 0,
    }
    reverse = True
    if parameters.sort_by == "confidence_score":
        rows.sort(key=lambda row: (category_priority.get(row.candidate_type, 0), row.confidence_score), reverse=reverse)
    elif parameters.sort_by == "return_60d":
        rows.sort(key=lambda row: (category_priority.get(row.candidate_type, 0), row.metrics.return_60d), reverse=reverse)
    else:
        rows.sort(key=lambda row: (category_priority.get(row.candidate_type, 0), row.surge_candidate_score), reverse=reverse)

    rows, duplicate_result_count = _dedupe_result_rows(rows)
    if duplicate_result_count:
        data_source_report["warnings"].append("duplicate_result_rows_deduped")
    matched_count = len(rows)
    rows = rows[: parameters.limit]
    for index, row in enumerate(rows, start=1):
        row.rank = index
    rate_limit_state = get_finmind_rate_limit_state()
    data_source_report["ohlcv"]["finmind_rate_limited"] = bool(rate_limit_state["finmind_rate_limited"])
    data_source_report["ohlcv"]["finmind_disabled_until"] = rate_limit_state["finmind_disabled_until"]
    funnel_report = _build_funnel_report(
        universe_size=len(universe),
        ohlcv_failures=debug_ohlcv_failures,
        evaluated_rows=debug_rows,
        parameters=parameters,
        rules=rules,
        data_source_report=data_source_report,
    ) if debug else None

    return ScreenerResponse(
        generated_at=datetime.now(TW_TIMEZONE).isoformat(),
        rule_set_version=str(require_rule(rules, "rule_set_version")),
        is_v1_hypothesis=bool(require_rule(rules, "is_v1_hypothesis")),
        universe_size=len(universe),
        matched_count=matched_count,
        summary=summary,
        parameters=parameters.to_dict(),
        data_warnings=warnings,
        results=rows,
        funnel_report=funnel_report,
        data_source_report=data_source_report if debug else None,
    )
