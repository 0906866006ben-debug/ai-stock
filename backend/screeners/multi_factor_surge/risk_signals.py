from __future__ import annotations

import pandas as pd

from backend.screeners.multi_factor_surge.config import CONFIG, clamp_score
from backend.screeners.multi_factor_surge.schemas import ModuleScore


def score_risk(df: pd.DataFrame, technical_metrics: dict[str, object]) -> tuple[ModuleScore, dict[str, object]]:
    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) >= 2 else latest
    high = float(latest["high"])
    low = float(latest["low"])
    close = float(latest["close"])
    open_price = float(latest["open"])
    volume = float(latest["volume"])
    avg_volume_20 = float(df["volume"].tail(20).mean())
    daily_range = high - low
    upper_shadow_ratio = (high - max(open_price, close)) / daily_range if daily_range else 0.0
    close_position = (close - low) / daily_range if daily_range else 0.5
    volume_ratio = volume / avg_volume_20 if avg_volume_20 else 0.0
    gap_up_pct = (open_price - float(prev["close"])) / float(prev["close"]) if float(prev["close"]) else 0.0
    ma20 = float(df["close"].rolling(20, min_periods=1).mean().iloc[-1])
    price_below_20ma = close < ma20
    return_5d = (close - float(df["close"].iloc[-5])) / float(df["close"].iloc[-5]) if len(df) >= 5 and float(df["close"].iloc[-5]) else 0.0

    flags: list[str] = []
    score = 25
    if upper_shadow_ratio > float(CONFIG["risk"]["upper_shadow_ratio"]) and volume_ratio > float(CONFIG["risk"]["upper_shadow_volume_ratio"]):
        flags.append("long_upper_shadow_on_high_volume")
        score += 25
    if float(technical_metrics.get("kd_k") or 0) >= float(CONFIG["risk"]["kd_extreme_threshold"]) and close_position < 0.5:
        flags.append("kd_rsi_extreme_no_followthrough")
        score += 18
    if gap_up_pct >= float(CONFIG["risk"]["gap_up_pct"]) and close_position < float(CONFIG["risk"]["gap_weak_close_position"]):
        flags.append("gap_up_exhaustion")
        score += 18
    if price_below_20ma:
        flags.append("price_below_20ma")
        score += 12
    if return_5d > float(CONFIG["risk"]["recent_overheat_return_5d"]):
        flags.append("recent_overheat")
        score += 20

    metrics = {
        "upper_shadow_ratio_today": round(upper_shadow_ratio, 4),
        "close_position_in_range": round(close_position, 4),
        "volume_today_ratio_20": round(volume_ratio, 4),
        "gap_up_pct": round(gap_up_pct, 4),
        "price_below_20ma": price_below_20ma,
        "return_5d": round(return_5d, 4),
    }
    return ModuleScore(score=clamp_score(score), risk_flags=flags), metrics
