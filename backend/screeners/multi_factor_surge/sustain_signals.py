from __future__ import annotations

import pandas as pd

from backend.screeners.multi_factor_surge.config import CONFIG, clamp_score
from backend.screeners.multi_factor_surge.schemas import ModuleScore


def score_sustain(df: pd.DataFrame) -> tuple[ModuleScore, dict[str, object]]:
    target_window = int(CONFIG["sustain"]["new_high_window"])
    window = min(target_window, len(df))
    flags: list[str] = []
    if window < target_window:
        flags.append("history_lt_200")

    lookback_days = int(CONFIG["sustain"]["new_high_count_days"])
    recent = df.tail(lookback_days)
    new_high_count = 0
    for idx in recent.index:
        start = max(0, idx - window + 1)
        if df.loc[idx, "close"] >= df.loc[start:idx, "close"].max():
            new_high_count += 1

    avg_days = int(CONFIG["sustain"]["volume_avg_days"])
    avg_volume = float(df["volume"].tail(avg_days).mean())
    today_volume = float(df["volume"].iloc[-1])
    prev_volume = float(df["volume"].iloc[-2]) if len(df) >= 2 else today_volume
    volume_surge_ratio = today_volume / avg_volume if avg_volume else 0.0
    prev_day_ratio = today_volume / prev_volume if prev_volume else 0.0

    score = 40
    reasons: list[str] = []
    if new_high_count >= int(CONFIG["sustain"]["new_high_count_min"]):
        score += 30
        reasons.append(f"近 {lookback_days} 日有 {new_high_count} 日創區間新高")
    if volume_surge_ratio >= float(CONFIG["sustain"]["volume_surge_ratio"]):
        score += 18
        reasons.append(f"突破量能為均量 {volume_surge_ratio:.2f} 倍")
    if prev_day_ratio >= float(CONFIG["sustain"]["volume_prev_day_ratio"]):
        score += 10
        reasons.append(f"今日量能為前日 {prev_day_ratio:.2f} 倍")

    metrics = {
        "new_high_count_in_5d": new_high_count,
        "new_high_window_used": window,
        "volume_surge_ratio": round(volume_surge_ratio, 4),
        "volume_prev_day_ratio": round(prev_day_ratio, 4),
        "avg_volume_20d_shares": round(avg_volume, 2),
    }
    return ModuleScore(score=clamp_score(score), reasons=reasons, data_quality_flags=flags), metrics
