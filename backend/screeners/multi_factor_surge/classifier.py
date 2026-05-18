from __future__ import annotations

from backend.screeners.multi_factor_surge.config import CONFIG
from backend.screeners.multi_factor_surge.schemas import ModuleScore


def classify_candidate(
    *,
    surge_score: int,
    risk_score: int,
    fundamental: ModuleScore,
    chip: ModuleScore,
    technical: ModuleScore,
    sustain: ModuleScore,
    liquidity_score: int,
    risk_flags: list[str],
) -> str:
    if risk_score >= int(CONFIG["risk"]["overheat_score"]) or any(flag in risk_flags for flag in ("long_upper_shadow_on_high_volume", "gap_up_exhaustion", "recent_overheat")):
        return "偏熱觀察"

    module_scores = [
        ("fundamental", fundamental),
        ("chip", chip),
        ("technical", technical),
        ("sustain", sustain),
    ]
    resonance_count = sum(
        1
        for _name, module in module_scores
        if not module.is_neutral_fallback and module.score >= int(CONFIG["classification"]["module_high_score"])
    )
    if (
        surge_score >= int(CONFIG["classification"]["multi_factor_score_min"])
        and resonance_count >= int(CONFIG["classification"]["multi_factor_modules_min"])
        and risk_score < int(CONFIG["risk"]["max_for_resonance"])
    ):
        return "多因子共振候選"

    if (
        technical.score >= int(CONFIG["classification"]["technical_initial_technical_min"])
        and sustain.score >= int(CONFIG["classification"]["technical_initial_sustain_min"])
        and (fundamental.is_neutral_fallback or chip.is_neutral_fallback)
    ):
        return "技術初動候選"

    if (
        not chip.is_neutral_fallback
        and chip.score >= int(CONFIG["classification"]["chip_candidate_chip_min"])
        and liquidity_score >= int(CONFIG["classification"]["chip_candidate_liquidity_min"])
        and technical.score >= int(CONFIG["classification"]["chip_candidate_technical_min"])
    ):
        return "籌碼推升候選"

    if (
        not fundamental.is_neutral_fallback
        and fundamental.score >= int(CONFIG["classification"]["fundamental_candidate_fundamental_min"])
        and technical.score >= int(CONFIG["classification"]["fundamental_candidate_technical_min"])
    ):
        return "基本面成長候選"

    return "不符合"
