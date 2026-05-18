from __future__ import annotations

from typing import Any

from backend.screeners.multi_factor_surge.config import CONFIG
from backend.screeners.multi_factor_surge.schemas import ModuleScore


def score_chips(_stock_id: str, _chip_payload: dict[str, Any] | None = None) -> tuple[ModuleScore, dict[str, Any]]:
    # PHASE_2: implement real broker-branch / concentration / dealer streak features.
    metrics = {
        "buy_sell_household_diff_neg_ratio_60d": None,
        "dealer_net_buy_streak": None,
        "concentration_60d": None,
        "concentration_5d_vs_20d": None,
    }
    return ModuleScore(
        score=int(CONFIG["chip"]["neutral_score"]),
        missing_data=["chip_data_unavailable"],
        is_neutral_fallback=True,
    ), metrics
