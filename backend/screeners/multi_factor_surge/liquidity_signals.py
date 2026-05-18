from __future__ import annotations

import pandas as pd

from backend.screeners.multi_factor_surge.config import CONFIG, clamp_score
from backend.screeners.multi_factor_surge.schemas import ModuleScore


def score_liquidity(df: pd.DataFrame) -> tuple[ModuleScore, dict[str, object]]:
    avg_volume_5d_shares = float(df["volume"].tail(5).mean())
    min_shares = float(CONFIG["liquidity"]["min_avg_volume_5d_shares"])
    passed = avg_volume_5d_shares >= min_shares
    ratio = avg_volume_5d_shares / min_shares if min_shares else 0.0
    score = 30 + min(70, ratio * 35)
    metrics = {
        "avg_volume_5d_shares": round(avg_volume_5d_shares, 2),
        "avg_volume_5d_lots": round(avg_volume_5d_shares / float(CONFIG["liquidity"]["lots_to_shares"]), 2),
        "liquidity_pass": passed,
    }
    reasons = [f"5 日均量 {metrics['avg_volume_5d_lots']:,.0f} 張"] if passed else []
    return ModuleScore(score=clamp_score(score), reasons=reasons), metrics
