from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


PillarStatus = Literal["Pass", "Weak", "Fail", "AI_Review_Required", "Neutral", "Insufficient_Data"]


class Evidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    pillar: str
    source_url: Optional[str] = None
    published_date: Optional[str] = None
    summary: str
    catalyst_type: Optional[str] = None


class ScreeningResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    stock_id: str
    as_of_date: str
    is_mock: bool = False
    candidate_grade: Literal["S", "A", "B", "C", "D"]
    canslim_match: str
    pillars: dict[str, PillarStatus]
    pillar_metrics: dict[str, str] = Field(default_factory=dict)
    scores: dict[str, int] = Field(default_factory=dict)
    market_regime: Literal["risk_on", "risk_off", "severe", "unknown"]
    n_catalyst_score: Optional[int] = None
    interpretation: str
    evidence: list[Evidence] = Field(default_factory=list)
    data_warnings: list[str] = Field(default_factory=list)
    needs_manual_review: list[str] = Field(default_factory=list)
    action_type: Literal["Watchlist Candidate", "Manual Review Required", "Track Only"]
    # Swing exit / invalidation layer (additive, verb-free conditions). structure_status
    # is a neutral observation of the swing setup's health, not a buy/sell instruction.
    exit_signals: list[str] = Field(default_factory=list)
    structure_status: Literal["intact", "profit_watch", "weakening", "invalidated"] = "intact"


class CanslimFactorScore(BaseModel):
    """One CANSLIM factor in the consolidated output. score is null when the
    factor's data is insufficient / requires review (never fabricated)."""
    model_config = ConfigDict(frozen=True)

    factor: Literal["C", "A", "N", "S", "L", "I", "M"]
    status: PillarStatus
    score: Optional[int] = None
    reason: str = ""
    data_used: list[str] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)


class CanslimReviewResult(BaseModel):
    """Output of the deterministic CANSLIM Reviewer/Judge agent."""
    model_config = ConfigDict(frozen=True)

    review_score: int = 0
    review_status: Literal["APPROVED", "NEEDS_REVISION", "REJECTED"] = "NEEDS_REVISION"
    dimension_scores: list[dict[str, Any]] = Field(default_factory=list)
    critical_issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    overconfidence_flags: list[str] = Field(default_factory=list)
    required_fixes: list[str] = Field(default_factory=list)
    final_comment: str = ""


class CanslimFullResult(BaseModel):
    """Consolidated, decision-support CANSLIM output. Derived additively from the
    validated ScreeningResult; embeds it for traceability. Grade is a match-degree
    label, NOT an OOS-validated trading tier — confidence is driven by extension
    (N-pillar) + regime + data quality, not by the grade letter."""
    model_config = ConfigDict(frozen=True)

    stock_id: str
    as_of_date: str
    overall_score: int = 0
    grade: Literal["S", "A", "B", "C", "D"]
    pass_status: Literal["PASS", "WATCHLIST", "FAIL", "INSUFFICIENT_DATA"]
    confidence: Literal["HIGH", "MEDIUM", "LOW"]
    risk_level: Literal["LOW", "MEDIUM", "HIGH"]
    per_factor_scores: list[CanslimFactorScore] = Field(default_factory=list)
    positive_reasons: list[str] = Field(default_factory=list)
    negative_reasons: list[str] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)
    invalidation_signals: list[str] = Field(default_factory=list)
    observation_conditions: list[str] = Field(default_factory=list)
    suggested_strategy: str = ""
    data_quality: Literal["HIGH", "MEDIUM", "LOW"] = "LOW"
    is_mock_or_fallback_data: bool = False
    reviewer_result: Optional[CanslimReviewResult] = None
    screening_result: ScreeningResult


class CandidateScores(BaseModel):
    liquidity_score: int
    price_position_score: int
    base_compression_score: int
    volume_score: int
    ema_convergence_score: int
    relative_strength_score: int
    canslim_signal: Optional[int] = None
    canslim_risk: Optional[int] = None
    canslim_confidence: Optional[int] = None


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
    # Phase 11: 0=no tiered entry, 1=CORE, 2=QUALITY, 3=PREMIUM.
    entry_tier: int = 0
    # Phase R2: user-facing alias for the legacy entry_tier. entry_tier remains
    # populated for backward compatibility with backtests and older clients.
    candidate_grade: Optional[str] = None
    canslim_grade: Optional[str] = None
    canslim_signal: Optional[int] = None
    canslim_risk: Optional[int] = None
    canslim_confidence: Optional[int] = None
    canslim_hard_blocked: Optional[bool] = None

    @model_validator(mode="after")
    def populate_candidate_grade_alias(self) -> "CandidateMetrics":
        if self.candidate_grade:
            return self
        if self.canslim_grade in {"S", "A", "B", "C", "D"}:
            self.candidate_grade = self.canslim_grade
            return self
        tier_labels = {
            3: "Premium",
            2: "Quality",
            1: "Core",
            0: "Unclassified",
        }
        self.candidate_grade = tier_labels.get(int(self.entry_tier or 0), "Unclassified")
        return self


class SurgeCandidateResult(BaseModel):
    rank: int = 0
    stock_id: str
    stock_name: str
    candidate_type: str
    screening_status: Optional[str] = None
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

    @model_validator(mode="after")
    def populate_screening_status_alias(self) -> "SurgeCandidateResult":
        if self.screening_status is None:
            self.screening_status = self.candidate_type
        return self


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
