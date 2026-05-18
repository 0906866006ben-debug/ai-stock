from __future__ import annotations

from threading import Lock
from time import time
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response

from backend.screeners.multi_factor_surge.config import CONFIG
from backend.screeners.multi_factor_surge.schemas import MultiFactorResponse
from backend.screeners.multi_factor_surge.service import (
    MultiFactorParameters,
    UniverseLoadError,
    scan_multi_factor_surge,
)


router = APIRouter(prefix="/screeners", tags=["screeners"])
_CACHE: dict[str, tuple[float, MultiFactorResponse]] = {}
_CACHE_LOCK = Lock()
_CACHE_TTL_SECONDS = 1800


def _make_cache_key(params: MultiFactorParameters) -> str:
    return repr(sorted(params.to_dict().items()))


def _get_cached(key: str) -> MultiFactorResponse | None:
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if not cached:
            return None
        cached_at, payload = cached
        if time() - cached_at > _CACHE_TTL_SECONDS:
            _CACHE.pop(key, None)
            return None
        return payload


def _set_cached(key: str, payload: MultiFactorResponse) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = (time(), payload)


@router.get("/multi-factor-surge", response_model=MultiFactorResponse)
async def multi_factor_surge(
    response: Response,
    limit: int = Query(50, ge=1, le=200),
    market: str = Query("all"),
    candidate_type: str | None = Query(None),
    min_surge_score: int = Query(0, ge=0, le=100),
    include_unfit: bool = Query(False),
    debug: bool = Query(False),
    force_refresh: bool = Query(False),
    scan_limit: int | None = Query(None, ge=1, le=10000),
) -> MultiFactorResponse:
    market = market.lower()
    if market not in CONFIG["universe"]["allowed_markets"]:
        raise HTTPException(status_code=422, detail="market must be all, twse, or tpex")
    allowed_types = {"多因子共振候選", "技術初動候選", "籌碼推升候選", "基本面成長候選", "偏熱觀察", "不符合"}
    if candidate_type and candidate_type not in allowed_types:
        raise HTTPException(status_code=422, detail="candidate_type is not supported")

    params = MultiFactorParameters(
        limit=limit,
        market=market,
        candidate_type=candidate_type,
        min_surge_score=min_surge_score,
        include_unfit=include_unfit,
        debug=debug,
        scan_limit=scan_limit,
    )
    cache_key = _make_cache_key(params)
    if not force_refresh:
        cached = _get_cached(cache_key)
        if cached is not None:
            response.headers["X-Cache"] = "hit"
            return cached
    try:
        payload = await scan_multi_factor_surge(params)
    except UniverseLoadError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    _set_cached(cache_key, payload)
    response.headers["X-Cache"] = "miss"
    return payload
