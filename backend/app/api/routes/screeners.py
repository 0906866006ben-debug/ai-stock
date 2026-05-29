from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response

from backend.app.models.screener_schemas import ScreenerResponse
from backend.app.services.screener_cache import (
    ForceRefreshRateLimited,
    check_force_refresh_allowed,
    get_cached_response,
    make_cache_key,
    set_cached_response,
)
from backend.app.services.screener_jobs import (
    cancel_job,
    complete_job,
    create_job,
    fail_job,
    get_job,
    is_job_cancelled,
    update_job,
    update_scan_progress,
)
from backend.app.services.screener_market_loader import load_taiex_history_with_source
from backend.app.services.screener_rules import load_surge_candidate_rules, require_rule
from backend.app.services.screener_service import (
    ScanCancelled,
    ScreenerParameters,
    UniverseLoadError,
    default_screener_parameters,
    scan_surge_candidates,
)


router = APIRouter(prefix="/screeners", tags=["screeners"])


def _cache_payload(params: ScreenerParameters, debug: bool) -> dict[str, Any]:
    payload = params.to_dict()
    if debug:
        payload["debug"] = True
    return payload


def _build_screener_parameters(
    min_return_60d: float | None = Query(None),
    max_return_60d: float | None = Query(None),
    max_base_return: float | None = Query(None),
    min_return_20d: float | None = Query(None),
    min_avg_volume_lots: int | None = Query(None),
    min_avg_turnover: int | None = Query(None),
    scan_limit: int | None = Query(None, ge=1),
    limit: int | None = Query(None, ge=1),
    market: str | None = Query(None),
    sort_by: str | None = Query(None),
    candidate_type: str | None = Query(None),
    include_unfit: bool = Query(False),
    ai_tech_only: bool = Query(True, description="Only show AI tech stocks (6-Layer Framework whitelist)"),
    include_canslim: bool = Query(False, description="Attach optional CAN SLIM observation fields"),
) -> ScreenerParameters:
    rules = load_surge_candidate_rules()
    defaults = default_screener_parameters()
    allowed_sort = {"surge_candidate_score", "confidence_score", "return_60d"}
    effective_sort = sort_by or defaults.sort_by
    if effective_sort not in allowed_sort:
        raise HTTPException(status_code=422, detail="sort_by must be surge_candidate_score, confidence_score, or return_60d.")
    if candidate_type and candidate_type not in {"初動觀察", "初動候選", "動能確認", "偏熱觀察", "不符合", "CANSLIM觀察"}:
        raise HTTPException(status_code=422, detail="candidate_type is not supported.")

    max_limit = int(require_rule(rules, "api.max_limit"))
    max_scan_limit = int(require_rule(rules, "api.max_scan_limit"))
    effective_limit = min(limit or defaults.limit, max_limit)
    effective_scan_limit = min(scan_limit or defaults.scan_limit, max_scan_limit)
    params = ScreenerParameters(
        min_return_60d=min_return_60d if min_return_60d is not None else defaults.min_return_60d,
        max_return_60d=max_return_60d if max_return_60d is not None else defaults.max_return_60d,
        max_base_return=max_base_return if max_base_return is not None else defaults.max_base_return,
        min_return_20d=min_return_20d if min_return_20d is not None else defaults.min_return_20d,
        min_avg_volume_lots=min_avg_volume_lots if min_avg_volume_lots is not None else defaults.min_avg_volume_lots,
        min_avg_turnover=min_avg_turnover if min_avg_turnover is not None else defaults.min_avg_turnover,
        scan_limit=effective_scan_limit,
        limit=effective_limit,
        market=(market or defaults.market).upper(),
        sort_by=effective_sort,
        candidate_type=candidate_type,
        include_unfit=include_unfit,
        ai_tech_only=ai_tech_only,
        include_canslim=include_canslim,
    )
    if params.market != "TW":
        raise HTTPException(status_code=422, detail="Only market=TW is supported in Phase 1.")
    return params


@router.get("/surge-candidates", response_model=ScreenerResponse)
async def surge_candidates(
    response: Response,
    min_return_60d: float | None = Query(None),
    max_return_60d: float | None = Query(None),
    max_base_return: float | None = Query(None),
    min_return_20d: float | None = Query(None),
    min_avg_volume_lots: int | None = Query(None),
    min_avg_turnover: int | None = Query(None),
    scan_limit: int | None = Query(None, ge=1),
    limit: int | None = Query(None, ge=1),
    market: str | None = Query(None),
    sort_by: str | None = Query(None),
    candidate_type: str | None = Query(None),
    include_unfit: bool = Query(False),
    ai_tech_only: bool = Query(True, description="Only show AI tech stocks (6-Layer Framework whitelist)"),
    include_canslim: bool = Query(False, description="Attach optional CAN SLIM observation fields"),
    force_refresh: bool = Query(False),
    debug: bool = Query(False),
) -> ScreenerResponse:
    params = _build_screener_parameters(
        min_return_60d=min_return_60d,
        max_return_60d=max_return_60d,
        max_base_return=max_base_return,
        min_return_20d=min_return_20d,
        min_avg_volume_lots=min_avg_volume_lots,
        min_avg_turnover=min_avg_turnover,
        scan_limit=scan_limit,
        limit=limit,
        market=market,
        sort_by=sort_by,
        candidate_type=candidate_type,
        include_unfit=include_unfit,
        ai_tech_only=ai_tech_only,
        include_canslim=include_canslim,
    )
    cache_key = make_cache_key(_cache_payload(params, debug))
    if not force_refresh:
        cached = get_cached_response(cache_key)
        if cached is not None:
            response.headers["X-Cache"] = "hit"
            return cached

    if force_refresh:
        try:
            check_force_refresh_allowed(cache_key)
        except ForceRefreshRateLimited as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc

    data_warnings: list[str] = []
    market_result = await load_taiex_history_with_source()
    df_market = market_result.dataframe if market_result.available else None
    if df_market is None:
        data_warnings.append("market_index_unavailable")

    try:
        result = await scan_surge_candidates(
            params,
            df_market=df_market,
            data_warnings=data_warnings,
            debug=debug,
            market_index_report=market_result.to_report(),
        )
    except UniverseLoadError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    set_cached_response(cache_key, result)
    response.headers["X-Cache"] = "miss"
    return result


@router.post("/surge-candidates/jobs")
async def start_surge_candidates_job(
    min_return_60d: float | None = Query(None),
    max_return_60d: float | None = Query(None),
    max_base_return: float | None = Query(None),
    min_return_20d: float | None = Query(None),
    min_avg_volume_lots: int | None = Query(None),
    min_avg_turnover: int | None = Query(None),
    scan_limit: int | None = Query(None, ge=1),
    limit: int | None = Query(None, ge=1),
    market: str | None = Query(None),
    sort_by: str | None = Query(None),
    candidate_type: str | None = Query(None),
    include_unfit: bool = Query(False),
    ai_tech_only: bool = Query(True, description="Only show AI tech stocks (6-Layer Framework whitelist)"),
    include_canslim: bool = Query(False, description="Attach optional CAN SLIM observation fields"),
    force_refresh: bool = Query(False),
    debug: bool = Query(False),
) -> dict[str, Any]:
    params = _build_screener_parameters(
        min_return_60d=min_return_60d,
        max_return_60d=max_return_60d,
        max_base_return=max_base_return,
        min_return_20d=min_return_20d,
        min_avg_volume_lots=min_avg_volume_lots,
        min_avg_turnover=min_avg_turnover,
        scan_limit=scan_limit,
        limit=limit,
        market=market,
        sort_by=sort_by,
        candidate_type=candidate_type,
        include_unfit=include_unfit,
        ai_tech_only=ai_tech_only,
        include_canslim=include_canslim,
    )
    cache_key = make_cache_key(_cache_payload(params, debug))
    if not force_refresh:
        cached = get_cached_response(cache_key)
        if cached is not None:
            snapshot = create_job(_cache_payload(params, debug))
            return complete_job(snapshot["job_id"], cached, "使用快取結果") or snapshot

    if force_refresh:
        try:
            check_force_refresh_allowed(cache_key)
        except ForceRefreshRateLimited as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc

    snapshot = create_job(_cache_payload(params, debug))
    job_id = snapshot["job_id"]

    async def run_job() -> None:
        update_job(job_id, status="running", progress_pct=1, message="正在載入大盤資料")
        data_warnings: list[str] = []
        def progress(payload: dict[str, Any]) -> bool:
            if is_job_cancelled(job_id):
                return False
            update_scan_progress(job_id, payload)
            return not is_job_cancelled(job_id)

        try:
            market_result = await load_taiex_history_with_source()
            df_market = market_result.dataframe if market_result.available else None
            if is_job_cancelled(job_id):
                return
            if df_market is None:
                data_warnings.append("market_index_unavailable")
            result = await scan_surge_candidates(
                params,
                df_market=df_market,
                data_warnings=data_warnings,
                progress_callback=progress,
                debug=debug,
                market_index_report=market_result.to_report(),
            )
            if is_job_cancelled(job_id):
                return
            set_cached_response(cache_key, result)
            complete_job(job_id, result)
        except ScanCancelled:
            cancel_job(job_id)
        except UniverseLoadError as exc:
            fail_job(job_id, str(exc))
        except Exception as exc:
            fail_job(job_id, str(exc))

    asyncio.create_task(run_job())
    return get_job(job_id) or snapshot


@router.get("/surge-candidates/jobs/{job_id}")
async def get_surge_candidates_job(job_id: str) -> dict[str, Any]:
    snapshot = get_job(job_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Screener job not found.")
    return snapshot


@router.post("/surge-candidates/jobs/{job_id}/cancel")
async def cancel_surge_candidates_job(job_id: str) -> dict[str, Any]:
    snapshot = cancel_job(job_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Screener job not found.")
    return snapshot
