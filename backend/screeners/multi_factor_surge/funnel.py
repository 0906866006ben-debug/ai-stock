from __future__ import annotations

from typing import Any

from backend.screeners.multi_factor_surge.config import CONFIG


def pass_rate(pass_count: int, fail_count: int) -> float:
    total = pass_count + fail_count
    return round(pass_count / total, 4) if total else 0.0


def condition_report(name: str, total: int, pass_count: int, failed: list[dict[str, Any]], reason: str) -> dict[str, Any]:
    fail_count = max(0, total - pass_count)
    return {
        "name": name,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "pass_rate": pass_rate(pass_count, fail_count),
        "top_failed_examples": failed[:10],
        "failed_reason": reason,
    }


class FunnelBuilder:
    def __init__(self) -> None:
        self.stages = {
            "universe_size": 0,
            "common_stock_filter_count": 0,
            "excluded_by_pattern_count": {"etf": 0, "warrant": 0, "preferred": 0, "ky": 0, "name_keyword": 0, "industry": 0, "market": 0},
            "ohlcv_sufficient_count": 0,
            "liquidity_pass_count": 0,
            "fundamental_data_available_count": 0,
            "fundamental_score_high_count": 0,
            "chip_data_available_count": 0,
            "chip_score_high_count": 0,
            "technical_score_high_count": 0,
            "sustain_score_high_count": 0,
            "risk_filter_pass_count": 0,
            "final_matched_count": 0,
            "error_count": 0,
        }
        self._failed: dict[str, list[dict[str, Any]]] = {
            "liquidity_avg_volume_5d>=500000_shares": [],
            "fundamental_score_high": [],
            "chip_score_high": [],
            "technical_score_high": [],
            "sustain_score_high": [],
            "risk_filter": [],
            "ohlcv_sufficient": [],
        }

    def initialize_universe(self, raw_size: int, common_size: int, breakdown: dict[str, int]) -> None:
        self.stages["universe_size"] = raw_size
        self.stages["common_stock_filter_count"] = common_size
        self.stages["excluded_by_pattern_count"] = breakdown

    def add_failed(self, condition: str, item: dict[str, Any]) -> None:
        self._failed.setdefault(condition, []).append(item)

    def build(self) -> dict[str, Any]:
        common_total = int(self.stages["common_stock_filter_count"])
        ohlcv_total = int(self.stages["ohlcv_sufficient_count"])
        conditions = [
            condition_report(
                "ohlcv_sufficient",
                common_total,
                int(self.stages["ohlcv_sufficient_count"]),
                sorted(self._failed["ohlcv_sufficient"], key=lambda item: item.get("bars_available", 0), reverse=True),
                f"bars_available < {CONFIG['history']['minimum_bars']}",
            ),
            condition_report(
                "liquidity_avg_volume_5d>=500000_shares",
                ohlcv_total,
                int(self.stages["liquidity_pass_count"]),
                sorted(self._failed["liquidity_avg_volume_5d>=500000_shares"], key=lambda item: item.get("avg_volume_5d_shares", 0), reverse=True),
                "avg_volume_5d_shares < 500000",
            ),
            condition_report("fundamental_score_high", ohlcv_total, int(self.stages["fundamental_score_high_count"]), self._failed["fundamental_score_high"], "fundamental_score < high threshold"),
            condition_report("chip_score_high", ohlcv_total, int(self.stages["chip_score_high_count"]), self._failed["chip_score_high"], "chip_score < high threshold or neutral fallback"),
            condition_report("technical_score_high", ohlcv_total, int(self.stages["technical_score_high_count"]), self._failed["technical_score_high"], "technical_score < high threshold"),
            condition_report("sustain_score_high", ohlcv_total, int(self.stages["sustain_score_high_count"]), self._failed["sustain_score_high"], "breakout_sustain_score < high threshold"),
            condition_report("risk_filter", ohlcv_total, int(self.stages["risk_filter_pass_count"]), self._failed["risk_filter"], "risk_score >= threshold or overheating flags present"),
        ]
        return {"stages": self.stages, "conditions": conditions}
