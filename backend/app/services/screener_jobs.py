from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any
from uuid import uuid4


TW_TIMEZONE = timezone(timedelta(hours=8))
JOB_TTL = timedelta(hours=2)
_LOCK = Lock()
_JOBS: dict[str, "ScreenerJob"] = {}


@dataclass
class ScreenerJob:
    job_id: str
    status: str
    progress_pct: int
    processed: int
    total: int
    message: str
    parameters: dict[str, Any]
    created_at: str
    updated_at: str
    current_stock_id: str | None = None
    current_stock_name: str | None = None
    result: Any | None = None
    error: str | None = None


def _now() -> datetime:
    return datetime.now(TW_TIMEZONE)


def _iso_now() -> str:
    return _now().isoformat()


def _serialize_model(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "dict"):
        return value.dict()
    return value


def _snapshot(job: ScreenerJob) -> dict[str, Any]:
    return {
        "job_id": job.job_id,
        "status": job.status,
        "progress_pct": job.progress_pct,
        "processed": job.processed,
        "total": job.total,
        "message": job.message,
        "parameters": job.parameters,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "current_stock_id": job.current_stock_id,
        "current_stock_name": job.current_stock_name,
        "result": _serialize_model(job.result),
        "error": job.error,
    }


def _cleanup_locked() -> None:
    cutoff = _now() - JOB_TTL
    expired_ids = []
    for job_id, job in _JOBS.items():
        try:
            updated = datetime.fromisoformat(job.updated_at)
        except ValueError:
            updated = _now()
        if updated < cutoff:
            expired_ids.append(job_id)
    for job_id in expired_ids:
        _JOBS.pop(job_id, None)


def create_job(parameters: dict[str, Any]) -> dict[str, Any]:
    job_id = uuid4().hex
    timestamp = _iso_now()
    job = ScreenerJob(
        job_id=job_id,
        status="queued",
        progress_pct=0,
        processed=0,
        total=0,
        message="等待開始掃描",
        parameters=parameters,
        created_at=timestamp,
        updated_at=timestamp,
    )
    with _LOCK:
        _cleanup_locked()
        _JOBS[job_id] = job
        return _snapshot(job)


def get_job(job_id: str) -> dict[str, Any] | None:
    with _LOCK:
        job = _JOBS.get(job_id)
        return _snapshot(job) if job else None


def update_job(job_id: str, **updates: Any) -> dict[str, Any] | None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return None
        if job.status == "cancelled" and updates.get("status") in {"running", "completed", "failed"}:
            return _snapshot(job)
        for key, value in updates.items():
            if hasattr(job, key):
                setattr(job, key, value)
        job.updated_at = _iso_now()
        return _snapshot(job)


def update_scan_progress(job_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    if is_job_cancelled(job_id):
        return get_job(job_id)
    processed = int(payload.get("processed") or 0)
    total = int(payload.get("total") or 0)
    progress_pct = 3
    if total > 0:
        progress_pct = min(99, max(3, int(round((processed / total) * 99))))
    return update_job(
        job_id,
        status="running",
        progress_pct=progress_pct,
        processed=processed,
        total=total,
        message=str(payload.get("message") or "掃描中"),
        current_stock_id=payload.get("current_stock_id"),
        current_stock_name=payload.get("current_stock_name"),
    )


def complete_job(job_id: str, result: Any, message: str = "掃描完成") -> dict[str, Any] | None:
    return update_job(
        job_id,
        status="completed",
        progress_pct=100,
        message=message,
        result=result,
        error=None,
    )


def fail_job(job_id: str, error: str) -> dict[str, Any] | None:
    return update_job(
        job_id,
        status="failed",
        message="掃描失敗",
        error=error,
    )


def cancel_job(job_id: str, message: str = "掃描已暫停") -> dict[str, Any] | None:
    return update_job(
        job_id,
        status="cancelled",
        message=message,
        error=None,
    )


def is_job_cancelled(job_id: str) -> bool:
    with _LOCK:
        job = _JOBS.get(job_id)
        return bool(job and job.status == "cancelled")
