"""Swing-trading exit / invalidation signal layer (screening surface, verb-free).

CANSLIM is a swing/intermediate-momentum method; the entry screen is only half the
edge — the other half is knowing when the swing setup has WEAKENED or been INVALIDATED.
This module turns the current live features into deterministic, condition-phrased
(verb-free) exit/invalidation observations. It does NOT change any signal/score/grade
math and it never issues buy/sell/hold/exit commands — only conditions the user reads.

All thresholds live in the YAML `exit:` block (tunable). A missing feature simply omits
that one signal (no fabrication); no signals → structure_status "intact".
"""
from __future__ import annotations

from typing import Any, Mapping

from backend.app.services.strategy.canslim.features import CanslimFeatures
from backend.app.services.strategy.canslim.screening_language import clean_string_list

# structure_status precedence (worst first); verb-free neutral enum.
StructureStatus = str  # Literal["intact","profit_watch","weakening","invalidated"]


def evaluate_swing_exit(features: CanslimFeatures | None, params: Mapping[str, Any]) -> dict[str, Any]:
    """Return {'exit_signals': list[str], 'structure_status': str} from live features."""
    if features is None:
        return {"exit_signals": [], "structure_status": "intact"}
    screening = params.get("screening", {}) if isinstance(params, Mapping) else {}
    cfg = screening.get("exit", {}) if isinstance(screening, Mapping) else {}
    signals: list[str] = []
    weakening = invalidated = profit_watch = False

    close = features.close
    ma20 = features.ma20
    ma60 = features.ma60

    # Trend breaks (short / mid). Below MA20 = swing short-term weakening; below the
    # mid MA = the intermediate swing structure is invalidated.
    if close is not None and ma20 is not None and close < ma20:
        signals.append("跌破20日均線:波段短期趨勢轉弱")
        weakening = True
    if close is not None and ma60 is not None and close < ma60:
        signals.append("跌破60日均線:波段中期結構失效")
        invalidated = True

    # Over-extension above the short MA = profit-taking observation zone (not a command).
    tp = float(cfg.get("extension_take_profit_pct", 0.15))
    if close is not None and ma20 is not None and ma20 > 0 and (close / ma20 - 1.0) >= tp:
        signals.append(f"距20日均線+{(close / ma20 - 1.0) * 100:.0f}%:波段延伸/獲利了結觀察區")
        profit_watch = True

    # Price-volume divergence: rising into the high but overall volume contracting.
    div_max = float(cfg.get("divergence_volume_ratio_max", 1.0))
    vexp = features.volume_ratio_recent_vs_prior_20
    near_high = features.pct_from_52w_high is not None and float(features.pct_from_52w_high) >= -0.10
    if vexp is not None and near_high and float(vexp) <= div_max:
        signals.append(f"價近高但量縮(近/前20日量比={float(vexp):.2f}):量價背離")
        weakening = True

    # Blow-off / overheating: extreme one-day volume spike while pinned near the high.
    spike_mult = float(cfg.get("overheat_volume_spike_mult", 4.0))
    if (
        features.latest_volume is not None and features.avg_volume_20
        and (float(features.latest_volume) / float(features.avg_volume_20)) >= spike_mult
        and features.pct_from_52w_high is not None and float(features.pct_from_52w_high) >= -0.03
    ):
        signals.append("急漲爆量過熱:追高/拉回風險")
        profit_watch = True

    if features.at_limit_up:
        signals.append("漲停鎖死:追高無法成交、拉回風險")
        profit_watch = True
    if features.at_limit_down:
        signals.append("跌停鎖死:流動性風險、型態轉弱")
        invalidated = True

    # Base/structure break: lost the recent consolidation floor.
    if close is not None and features.box_low_20 is not None and close < float(features.box_low_20):
        signals.append("跌破近20日盤整低點:型態失效")
        invalidated = True

    if invalidated:
        status = "invalidated"
    elif profit_watch and not weakening:
        status = "profit_watch"
    elif weakening:
        status = "weakening"
    elif profit_watch:
        status = "profit_watch"
    else:
        status = "intact"

    return {"exit_signals": clean_string_list(signals), "structure_status": status}
