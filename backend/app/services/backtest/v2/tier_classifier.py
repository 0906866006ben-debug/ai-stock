"""S/A/B/C entry tier classification for optimization v2."""
from __future__ import annotations

import math
from enum import IntEnum
from pathlib import Path
from typing import Any, Mapping

import yaml


class EntryTier(IntEnum):
    NONE = 0
    C = 1
    B = 2
    A = 3
    S = 4


DEFAULT_THRESHOLDS_PATH = Path(__file__).with_name("tier_thresholds.yaml")
_TIER_ORDER_DESC = (EntryTier.S, EntryTier.A, EntryTier.B, EntryTier.C)


def load_tier_thresholds(path: str | Path | None = None) -> dict[str, Any]:
    """Load tier thresholds from YAML."""
    threshold_path = Path(path) if path else DEFAULT_THRESHOLDS_PATH
    with threshold_path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    data.setdefault("tiers", {})
    data.setdefault("position_multipliers", {"C": 0.3, "B": 0.7, "A": 1.0, "S": 1.5})
    return data


def parse_entry_tier(value: EntryTier | int | str | None) -> EntryTier:
    """Parse letter or legacy integer tier input."""
    if value is None:
        return EntryTier.NONE
    if isinstance(value, EntryTier):
        return value
    if isinstance(value, bool):
        raise ValueError(f"invalid entry tier: {value!r}")
    if isinstance(value, int):
        return EntryTier(value)
    text = str(value).strip().upper()
    if not text:
        return EntryTier.NONE
    if text.isdigit() or (text.startswith("-") and text[1:].isdigit()):
        return EntryTier(int(text))
    if text.startswith("TIER_"):
        text = text.removeprefix("TIER_")
    aliases = {
        "NONE": EntryTier.NONE,
        "N": EntryTier.NONE,
        "0": EntryTier.NONE,
        "C": EntryTier.C,
        "B": EntryTier.B,
        "A": EntryTier.A,
        "S": EntryTier.S,
    }
    try:
        return aliases[text]
    except KeyError as exc:
        raise ValueError(f"invalid entry tier: {value!r}") from exc


def position_multiplier(
    tier: EntryTier | int | str,
    multipliers: Mapping[str | int, float] | None = None,
) -> float:
    """Return configured position multiplier for a tier."""
    parsed = parse_entry_tier(tier)
    if parsed == EntryTier.NONE:
        return 0.0
    configured = multipliers or {"C": 0.3, "B": 0.7, "A": 1.0, "S": 1.5}
    for key in (parsed.name, int(parsed)):
        if key in configured:
            return float(configured[key])
    return float({"C": 0.3, "B": 0.7, "A": 1.0, "S": 1.5}[parsed.name])


def classify_tier(
    features: Mapping[str, Any],
    scores: Mapping[str, Any] | None = None,
    risk_score: int | float | None = None,
    thresholds: Mapping[str, Any] | None = None,
) -> EntryTier:
    """Return the highest S/A/B/C tier whose cumulative conditions pass."""
    loaded = thresholds or load_tier_thresholds()
    tier_cfg = dict(loaded.get("tiers", loaded))

    if risk_score is None:
        risk_score = _number(_lookup(features, scores, "risk_score"), default=100.0)

    for tier in _TIER_ORDER_DESC:
        if all(_passes_level(level, features, scores, float(risk_score), tier_cfg) for level in _levels_for(tier)):
            return tier
    return EntryTier.NONE


def _levels_for(tier: EntryTier) -> tuple[str, ...]:
    if tier == EntryTier.C:
        return ("C",)
    if tier == EntryTier.B:
        return ("C", "B")
    if tier == EntryTier.A:
        return ("C", "B", "A")
    if tier == EntryTier.S:
        return ("C", "B", "A", "S")
    return ()


def _passes_level(
    level: str,
    features: Mapping[str, Any],
    scores: Mapping[str, Any] | None,
    risk_score: float,
    thresholds: Mapping[str, Mapping[str, Any]],
) -> bool:
    cfg = thresholds.get(level, {})
    if level == "C":
        range_90d = _number(_lookup(features, scores, "range_90d", "range_90d_pct", "range_pct_90d"))
        volume_contraction = _number(_lookup(features, scores, "volume_contraction_ratio", "vol_contraction_ratio"))
        ema_spread = _number(_lookup(features, scores, "ema_spread", "ema_spread_pct"))
        close = _number(_lookup(features, scores, "close", "close_price", "close_today"))
        base_high = _number(_lookup(features, scores, "base_high", "box_high", "range_high"))
        close_to_base_high = _number(
            _lookup(features, scores, "close_to_base_high", "close_to_base_high_ratio"),
            default=close / base_high if base_high > 0 else math.inf,
        )
        avg_turnover = _number(_lookup(features, scores, "avg_turnover_20", "avg_turnover", "turnover_20d"))
        return_90d = _number(_lookup(features, scores, "return_90d", "return_90d_pct", "momentum_90d"))
        buffer = float(cfg.get("breakout_pivot_buffer", 0.0))
        return (
            _between(range_90d, cfg.get("range_90d_min", 0.10), cfg.get("range_90d_max", 0.30))
            and volume_contraction <= float(cfg.get("volume_contraction_ratio_max", 1.0))
            and ema_spread <= float(cfg.get("ema_spread_max", 0.08))
            and base_high > 0
            and close > base_high * (1.0 + buffer)
            and close_to_base_high <= float(cfg.get("close_to_base_high_max", 1.08))
            and avg_turnover >= float(cfg.get("avg_turnover_20_min", 30_000_000))
            and return_90d >= float(cfg.get("return_90d_min", -0.25))
        )

    if level == "B":
        ema_spread = _number(_lookup(features, scores, "ema_spread", "ema_spread_pct"))
        slopes = (
            _number(_lookup(features, scores, "ema5_slope", "ema_5_slope")),
            _number(_lookup(features, scores, "ema10_slope", "ema_10_slope")),
            _number(_lookup(features, scores, "ema20_slope", "ema_20_slope")),
        )
        base_range_pct = _number(_lookup(features, scores, "base_range_pct", "box_range_pct"))
        volume_multiple = _volume_multiple(features, scores)
        pre_breakout = _number(_lookup(features, scores, "pre_breakout_score", "prebreakout_score"))
        slope_min = float(cfg.get("ema_slope_min", 0.0))
        return (
            ema_spread <= float(cfg.get("ema_spread_max", 0.05))
            and all(slope >= slope_min for slope in slopes)
            and base_range_pct <= float(cfg.get("base_range_pct_max", 0.15))
            and volume_multiple >= float(cfg.get("volume_today_vs_avg_vol_50_min", 1.2))
            and pre_breakout >= float(cfg.get("pre_breakout_score_min", 50))
            and risk_score < float(cfg.get("risk_score_max_exclusive", 70))
        )

    if level == "A":
        volume_multiple = _volume_multiple(features, scores)
        pre_breakout = _number(_lookup(features, scores, "pre_breakout_score", "prebreakout_score"))
        ema_upturn = _number(_lookup(features, scores, "ema_micro_upturn_score"))
        compression = _number(_lookup(features, scores, "base_compression_score"))
        avg_turnover = _number(_lookup(features, scores, "avg_turnover_20", "avg_turnover", "turnover_20d"))
        return (
            volume_multiple >= float(cfg.get("volume_today_vs_avg_vol_50_min", 1.4))
            and pre_breakout >= float(cfg.get("pre_breakout_score_min", 60))
            and ema_upturn >= float(cfg.get("ema_micro_upturn_score_min", 50))
            and compression >= float(cfg.get("base_compression_score_min", 50))
            and avg_turnover >= float(cfg.get("avg_turnover_20_min", 70_000_000))
        )

    if level == "S":
        volume_multiple = _volume_multiple(features, scores)
        pre_breakout = _number(_lookup(features, scores, "pre_breakout_score", "prebreakout_score"))
        ema_upturn = _number(_lookup(features, scores, "ema_micro_upturn_score"))
        compression = _number(_lookup(features, scores, "base_compression_score"))
        transition = _number(_lookup(features, scores, "ema_down_to_up_transition_score", "ema_transition_score"))
        avg_turnover = _number(_lookup(features, scores, "avg_turnover_20", "avg_turnover", "turnover_20d"))
        trend_template = _truthy(_lookup(features, scores, "trend_template_ok", "minervini_trend_template_ok"))
        return (
            volume_multiple >= float(cfg.get("volume_today_vs_avg_vol_50_min", 1.5))
            and pre_breakout >= float(cfg.get("pre_breakout_score_min", 70))
            and ema_upturn >= float(cfg.get("ema_micro_upturn_score_min", 60))
            and compression >= float(cfg.get("base_compression_score_min", 60))
            and transition >= float(cfg.get("ema_down_to_up_transition_score_min", 50))
            and avg_turnover >= float(cfg.get("avg_turnover_20_min", 100_000_000))
            and trend_template is bool(cfg.get("trend_template_ok", True))
        )

    return False


def _volume_multiple(features: Mapping[str, Any], scores: Mapping[str, Any] | None) -> float:
    existing = _lookup(
        features,
        scores,
        "volume_today_vs_avg_vol_50",
        "volume_multiple",
        "relative_volume_50d",
    )
    if existing is not None:
        return _number(existing)
    volume_today = _number(_lookup(features, scores, "volume_today", "volume_today_shares", "volume"))
    avg_volume = _number(_lookup(features, scores, "avg_vol_50", "avg_volume_50", "avg_volume_50_shares"))
    if avg_volume <= 0:
        return 0.0
    return volume_today / avg_volume


def _lookup(
    features: Mapping[str, Any],
    scores: Mapping[str, Any] | None,
    *keys: str,
) -> Any:
    for source in (features, scores or {}):
        for key in keys:
            if key in source:
                value = source[key]
                if value is not None:
                    return value
    return None


def _number(value: Any, *, default: float = math.inf) -> float:
    if value is None:
        return default
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(out):
        return default
    return out


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "ok", "pass"}
    return bool(value)


def _between(value: float, low: Any, high: Any) -> bool:
    return float(low) <= value <= float(high)

