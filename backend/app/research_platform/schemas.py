from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class DataTier(StrEnum):
    FULL_DERIVATIVES = "DATA_TIER_A_FULL_DERIVATIVES"
    NO_HISTORICAL_OI = "DATA_TIER_B_NO_HISTORICAL_OI"
    PRICE_FUNDING_ONLY = "DATA_TIER_C_PRICE_FUNDING_ONLY"
    PRICE_ONLY = "DATA_TIER_D_PRICE_ONLY"
    INVALID = "INVALID_DATA"


class ServiceState(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    NOT_VERIFIED = "NOT_VERIFIED"


class OrchestratorState(StrEnum):
    IDLE = "IDLE"
    SYNCING_DATA = "SYNCING_DATA"
    VALIDATING_DATA = "VALIDATING_DATA"
    RUNNING_BASELINES = "RUNNING_BASELINES"
    SEARCHING_PARAMETERS = "SEARCHING_PARAMETERS"
    VALIDATING_CANDIDATES = "VALIDATING_CANDIDATES"
    WAITING_FOR_OPENAI_EVENT = "WAITING_FOR_OPENAI_EVENT"
    APPLYING_APPROVED_PATCH = "APPLYING_APPROVED_PATCH"
    PAUSED = "PAUSED"
    DEGRADED = "DEGRADED"
    ERROR = "ERROR"


class ComponentHealth(BaseModel):
    name: str
    state: ServiceState
    observed_at: datetime
    detail: str | None = None


class IntervalCoverage(BaseModel):
    interval: str
    rows: int
    symbols: int
    start_at: datetime | None
    end_at: datetime | None


class DataAssetSummary(BaseModel):
    asset_id: str
    path: str
    source: str
    data_tier: DataTier
    bytes: int
    fingerprint: str
    intervals: list[IntervalCoverage]
    funding_rows: int
    funding_symbols: int
    funding_start_at: datetime | None
    funding_end_at: datetime | None
    oi_available: bool
    premium_available: bool
    sampled_ohlc_violations: int
    is_read_only_import: bool = True
    is_stale: bool
    observed_at: datetime
    warnings: list[str] = Field(default_factory=list)


class UniverseSymbol(BaseModel):
    symbol: str
    pair: str | None = None
    base_asset: str
    quote_asset: str
    contract_type: str
    status: str
    onboard_date: int | None = None
    delivery_date: int | None = None
    tick_size: str | None = None
    step_size: str | None = None
    minimum_quantity: str | None = None
    minimum_notional: str | None = None
    funding_interval_hours: int | None = None


class UniverseSnapshotResponse(BaseModel):
    snapshot_id: str
    observed_at: datetime
    source: str
    symbols: list[UniverseSymbol]
    historical_completeness: Literal["CURRENT_SNAPSHOT_ONLY", "PARTIAL_HISTORY", "COMPLETE_HISTORY"]
    warnings: list[str] = Field(default_factory=list)


class ExperimentSummary(BaseModel):
    experiment_id: str
    variant: str
    hypothesis: str
    period_start: datetime | None
    period_end: datetime | None
    dataset_role: Literal["TRAIN", "VALIDATION", "LOCKED_OR_FORWARD_EVIDENCE", "UNKNOWN"]
    tuning_allowed: bool
    trades: int
    win_rate: float | None
    total_r: float
    average_r: float | None
    profit_factor: float | None
    net_pnl: float
    cagr: float | None
    max_drawdown_r: float | None
    sharpe: float | None
    exposure: float | None
    turnover: float | None
    source_path: str
    artifact_hash: str
    data_version: str
    engine_version: str
    imported_at: datetime
    is_mock: bool = False
    warnings: list[str] = Field(default_factory=list)


class FactorFinding(BaseModel):
    factor: Literal["FUNDING", "OPEN_INTEREST", "EMA", "VOLUME", "RSI"]
    status: Literal["UNAVAILABLE", "INSUFFICIENT_EVIDENCE", "NEGATIVE", "MIXED", "POSITIVE"]
    marginal_expectancy: float | None = None
    evidence_strength: Literal["NONE", "LOW", "MEDIUM", "HIGH"]
    applicable_scope: str
    reason: str
    invalidation: str
    source_experiment_ids: list[str] = Field(default_factory=list)
    observed_at: datetime


class CandidateSummary(BaseModel):
    strategy_id: str
    level: str
    research_score: float
    oos_expectancy: float | None
    profit_factor: float | None
    max_drawdown: float | None
    risk_level: Literal["LOW", "MEDIUM", "HIGH"]
    confidence: Literal["LOW", "MEDIUM", "HIGH"]
    invalidation: str
    warnings: list[str] = Field(default_factory=list)


class OpenAIUsageSummary(BaseModel):
    month: str
    automatic_calls: int
    manual_calls: int
    total_calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    target_usd: float
    hard_stop_usd: float
    hard_stop_reached: bool
    api_configured: bool
    deferred_events: int


class SystemStatusResponse(BaseModel):
    state: OrchestratorState
    paused: bool
    edge_status: Literal["NO ROBUST EDGE FOUND", "CANDIDATE EVIDENCE UNDER REVIEW"]
    live_trading_enabled: bool
    components: list[ComponentHealth]
    updated_at: datetime
    warnings: list[str] = Field(default_factory=list)


class DashboardOverview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    source: str
    is_mock: bool = False
    system: SystemStatusResponse
    data_assets: list[DataAssetSummary]
    symbols_scanned: int
    experiments_completed: int
    backtests_running: int
    queued_jobs: int
    best_candidate: CandidateSummary | None
    factor_findings: list[FactorFinding]
    openai: OpenAIUsageSummary
    warnings: list[str] = Field(default_factory=list)


class PaginatedExperiments(BaseModel):
    items: list[ExperimentSummary]
    total: int
    limit: int
    offset: int


class JobSummary(BaseModel):
    job_id: str
    job_type: str
    state: str
    priority: int
    attempts: int
    created_at: datetime
    updated_at: datetime
    payload: dict[str, Any] = Field(default_factory=dict)


class WorkerHeartbeat(BaseModel):
    worker_id: str
    worker_type: str
    state: str
    current_job_id: str | None = None
    process_id: int
    started_at: datetime
    heartbeat_at: datetime


class CycleStartResponse(BaseModel):
    accepted: bool
    cycle_key: str
    job_ids: list[str]
    message: str
    request_id: str
    created_at: datetime


class ActionResponse(BaseModel):
    accepted: bool
    state: OrchestratorState
    message: str
    request_id: str
    updated_at: datetime


class ErrorResponse(BaseModel):
    error: dict[str, Any]
    request_id: str
