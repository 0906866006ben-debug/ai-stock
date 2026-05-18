from __future__ import annotations

from backend.screeners.multi_factor_surge.config import CONFIG, clamp_score
from backend.screeners.multi_factor_surge.schemas import ModuleScore, MultiFactorScores


def composite_scores(
    fundamental: ModuleScore,
    chip: ModuleScore,
    technical: ModuleScore,
    sustain: ModuleScore,
    liquidity: ModuleScore,
    risk: ModuleScore,
    missing_data: list[str],
    data_quality_flags: list[str],
) -> tuple[MultiFactorScores, int, int, int]:
    scores = MultiFactorScores(
        fundamental_score=fundamental.score,
        chip_score=chip.score,
        technical_score=technical.score,
        breakout_sustain_score=sustain.score,
        liquidity_score=liquidity.score,
    )
    weights = CONFIG["scoring"]["weights"]
    raw = (
        scores.fundamental_score * float(weights["fundamental_score"])
        + scores.chip_score * float(weights["chip_score"])
        + scores.technical_score * float(weights["technical_score"])
        + scores.breakout_sustain_score * float(weights["breakout_sustain_score"])
        + scores.liquidity_score * float(weights["liquidity_score"])
        + risk.score * float(weights["risk_score"])
    )
    confidence = int(CONFIG["confidence"]["base"])
    if "chip_data_unavailable" in missing_data:
        confidence -= int(CONFIG["confidence"]["chip_missing_penalty"])
    fundamental_missing = sum(1 for item in ("eps_unavailable", "revenue_unavailable", "roe_unavailable") if item in missing_data)
    if fundamental_missing == 3:
        confidence -= int(CONFIG["confidence"]["fundamental_all_missing_penalty"])
    else:
        confidence -= fundamental_missing * int(CONFIG["confidence"]["fundamental_missing_each_penalty"])
    if "history_lt_200" in data_quality_flags:
        confidence -= int(CONFIG["confidence"]["history_lt_200_penalty"])
    return scores, risk.score, clamp_score(confidence), clamp_score(raw)
