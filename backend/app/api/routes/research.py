from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone
from functools import lru_cache

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status

from backend.app.research_platform.schemas import (
    ActionResponse,
    CandidateSummary,
    CycleStartResponse,
    DashboardOverview,
    DataAssetSummary,
    FactorFinding,
    JobSummary,
    OpenAIUsageSummary,
    PaginatedExperiments,
    SystemStatusResponse,
    UniverseSnapshotResponse,
    ValidationGate,
    WorkerHeartbeat,
)
from backend.app.research_platform.orchestrator import ResearchOrchestrator
from backend.app.research_platform.service import ResearchPlatformService


router = APIRouter(prefix="/api/v1", tags=["research-platform"])


@lru_cache(maxsize=1)
def get_research_service() -> ResearchPlatformService:
    return ResearchPlatformService()


def _request_id(request: Request) -> str:
    return request.headers.get("X-Request-ID", "").strip() or str(uuid.uuid4())


def require_mutation_token(
    authorization: str | None = Header(default=None),
    service: ResearchPlatformService = Depends(get_research_service),
) -> None:
    expected = service.settings.api_token
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "RESEARCH_AUTH_NOT_CONFIGURED", "message": "Mutation API is disabled until a backend token is configured."},
        )
    scheme, _, value = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(value, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": "A valid bearer token is required."},
            headers={"WWW-Authenticate": "Bearer"},
        )


def require_read_token(
    authorization: str | None = Header(default=None),
    service: ResearchPlatformService = Depends(get_research_service),
) -> None:
    if not service.settings.require_read_auth:
        return
    expected = service.settings.api_token
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "RESEARCH_AUTH_NOT_CONFIGURED", "message": "Read API authentication is enabled without a backend token."},
        )
    scheme, _, value = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(value, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": "A valid bearer token is required."},
            headers={"WWW-Authenticate": "Bearer"},
        )


@router.get("/health")
def research_health() -> dict[str, str]:
    return {"status": "ok", "service": "ai-stock-research-api", "version": "0.1.0"}


@router.get("/system/status", response_model=SystemStatusResponse, dependencies=[Depends(require_read_token)])
def system_status(service: ResearchPlatformService = Depends(get_research_service)) -> SystemStatusResponse:
    service.ensure_bootstrapped()
    return service.system_status()


@router.post("/system/pause", response_model=ActionResponse, dependencies=[Depends(require_mutation_token)])
def pause_system(request: Request, service: ResearchPlatformService = Depends(get_research_service)) -> ActionResponse:
    state, updated_at = service.pause()
    return ActionResponse(accepted=True, state=state, message="Research scheduling paused.", request_id=_request_id(request), updated_at=updated_at)


@router.post("/system/resume", response_model=ActionResponse, dependencies=[Depends(require_mutation_token)])
def resume_system(request: Request, service: ResearchPlatformService = Depends(get_research_service)) -> ActionResponse:
    state, updated_at = service.resume()
    return ActionResponse(accepted=True, state=state, message="Research scheduling resumed.", request_id=_request_id(request), updated_at=updated_at)


@router.get("/dashboard/overview", response_model=DashboardOverview, dependencies=[Depends(require_read_token)])
def dashboard_overview(service: ResearchPlatformService = Depends(get_research_service)) -> DashboardOverview:
    return service.dashboard_overview()


@router.get("/market/data-health", response_model=list[DataAssetSummary], dependencies=[Depends(require_read_token)])
def data_health(service: ResearchPlatformService = Depends(get_research_service)) -> list[DataAssetSummary]:
    service.ensure_bootstrapped()
    return service.repository.list_assets()


@router.get("/market/universe", response_model=UniverseSnapshotResponse | None, dependencies=[Depends(require_read_token)])
def market_universe(service: ResearchPlatformService = Depends(get_research_service)) -> UniverseSnapshotResponse | None:
    return service.current_universe()


@router.post(
    "/market/universe/refresh",
    response_model=UniverseSnapshotResponse,
    dependencies=[Depends(require_mutation_token)],
)
def refresh_market_universe(
    service: ResearchPlatformService = Depends(get_research_service),
) -> UniverseSnapshotResponse:
    return service.refresh_universe()


@router.get("/research/experiments", response_model=PaginatedExperiments, dependencies=[Depends(require_read_token)])
def experiments(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    service: ResearchPlatformService = Depends(get_research_service),
) -> PaginatedExperiments:
    return service.experiments(limit, offset)


@router.get("/research/validation-gates", response_model=list[ValidationGate], dependencies=[Depends(require_read_token)])
def research_validation_gates(
    service: ResearchPlatformService = Depends(get_research_service),
) -> list[ValidationGate]:
    return service.validation_gates()


@router.post("/research/start-cycle", response_model=CycleStartResponse, dependencies=[Depends(require_mutation_token)])
def start_research_cycle(
    request: Request,
    service: ResearchPlatformService = Depends(get_research_service),
) -> CycleStartResponse:
    now = datetime.now(timezone.utc)
    cycle_key = now.strftime("manual:%Y-%m-%dT%H")
    job_ids = ResearchOrchestrator(service=service).schedule_cycle(cycle_key)
    return CycleStartResponse(
        accepted=True,
        cycle_key=cycle_key,
        job_ids=job_ids,
        message="Data catalog and current-universe refresh jobs were queued. No locked test or trading job was created.",
        request_id=_request_id(request),
        created_at=now,
    )


@router.get("/strategies/candidates", response_model=list[CandidateSummary], dependencies=[Depends(require_read_token)])
def candidates(service: ResearchPlatformService = Depends(get_research_service)) -> list[CandidateSummary]:
    return service.repository.list_candidates()


@router.get("/strategies/{strategy_id}/factor-findings", response_model=list[FactorFinding], dependencies=[Depends(require_read_token)])
def factor_findings(strategy_id: str, service: ResearchPlatformService = Depends(get_research_service)) -> list[FactorFinding]:
    del strategy_id
    service.ensure_bootstrapped()
    return service.repository.list_factor_findings()


@router.get("/workers", response_model=list[WorkerHeartbeat], dependencies=[Depends(require_read_token)])
def workers(service: ResearchPlatformService = Depends(get_research_service)) -> list[WorkerHeartbeat]:
    return service.repository.list_workers()


@router.get("/jobs", response_model=list[JobSummary], dependencies=[Depends(require_read_token)])
def jobs(service: ResearchPlatformService = Depends(get_research_service)) -> list[JobSummary]:
    return service.repository.list_jobs()


@router.get("/openai/usage", response_model=OpenAIUsageSummary, dependencies=[Depends(require_read_token)])
def openai_usage(service: ResearchPlatformService = Depends(get_research_service)) -> OpenAIUsageSummary:
    return service.budget.summary()
