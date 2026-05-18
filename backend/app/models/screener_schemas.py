from typing import Any, Optional

from pydantic import BaseModel, Field


class CandidateScores(BaseModel):
    liquidity_score: int
    price_position_score: int
    base_compression_score: int
    volume_score: int
    ema_convergence_score: int
    relative_strength_score: int


class CandidateMetrics(BaseModel):
    return_60d: float
    return_90d: Optional[float] = None
    return_20d: float
    return_60_to_20: float
    return_5d: float
    # 90 日擺盪幅度 (high/low range) — 主力表態判定指標
    range_90d: float = 0.0
    high_90d: float = 0.0
    low_90d: float = 0.0
    # AI 框架族群分類
    sector_category: Optional[str] = None      # e.g. "cat_3_packaging"
    sector_label: Optional[str] = None         # e.g. "先進封裝/測試"
    avg_volume_20_lots: float
    avg_turnover_20: float
    base_high: float
    base_low: float
    base_range_pct: float
    volume_contraction_ratio: float
    volume_recovery_ratio_5d: float
    volume_today_ratio_20: float
    ema_spread: float
    ema5_slope: float
    ema10_slope: float
    ema20_slope: float
    # Prev-period slopes — for detecting 由弱轉強 (down→up turnaround)
    ema5_slope_prev_10d: float = 0.0
    ema10_slope_prev_10d: float = 0.0
    ema20_slope_prev_20d: float = 0.0
    ema_down_to_up_transition_score: int = 0
    relative_strength_20d: Optional[float]
    relative_strength_60d: Optional[float]
    downside_resilience_20d: Optional[float] = None
    close_distance_from_ema20: float
    close_from_ema20_pct: float = 0.0
    close_to_base_high_ratio: float = 0.0
    close_from_base_low_pct: float = 0.0
    pre_breakout_score: int = 0
    setup_price_position_score: int = 0
    ema_micro_upturn_score: int = 0
    volume_setup_score: int = 0
    volume_contraction_score: int = 0
    upper_shadow_ratio_today: float = 0.0
    # Rolling base detection — scan last 20/30/40 bars and pick the best consolidation
    recent_base_score: int = 0
    recent_base_window_bars: int = 0
    recent_base_range_pct: float = 0.0
    recent_base_contraction_ratio: float = 1.0


class SurgeCandidateResult(BaseModel):
    rank: int = 0
    stock_id: str
    stock_name: str
    candidate_type: str
    surge_candidate_score: int
    confidence_score: int
    risk_score: int
    scores: CandidateScores
    metrics: CandidateMetrics
    reasons: list[str]
    watch_conditions: list[str]
    invalidation: list[str]
    risk_flags: list[str]
    missing_data: list[str]
    data_quality_flags: list[str]
    source_info: dict[str, Any] = Field(default_factory=dict)
    extras: dict[str, Any] = Field(default_factory=dict)


class ScreenerResponse(BaseModel):
    strategy: str = "Taiwan Surge Candidate Screener v1"
    generated_at: str
    rule_set_version: str = "v1.0.0"
    is_v1_hypothesis: bool = True
    disclaimer: str = "This is a condition-based watch list, not investment advice or a buy/sell trading signal."
    universe_size: int
    matched_count: int
    summary: dict[str, int] = Field(default_factory=lambda: {
        "起漲前觀察": 0,
        "初動觀察": 0,
        "初動候選": 0,
        "動能確認": 0,
        "偏熱觀察": 0,
        "不符合": 0,
    })
    parameters: dict[str, Any]
    data_warnings: list[str]
    results: list[SurgeCandidateResult]
    funnel_report: Optional[dict[str, Any]] = None
    data_source_report: Optional[dict[str, Any]] = None
