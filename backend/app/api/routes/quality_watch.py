from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from backend.app.models.quality_snapshot import QualityWatchHistoryItem, QuarterlySnapshot
from backend.app.services.quality_snapshot_store import QualitySnapshotStore


router = APIRouter(prefix="/tw/quality-watch", tags=["quality-watch"])


@router.get("", response_model=QuarterlySnapshot)
async def get_quality_watch_snapshot(
    quarter: str = Query(..., description="Quarter identifier, e.g. 2026-Q1"),
) -> QuarterlySnapshot:
    snapshot = QualitySnapshotStore().read_snapshot(quarter)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"quality snapshot not found: {quarter}")
    return snapshot


@router.get("/latest", response_model=QuarterlySnapshot)
async def get_latest_quality_watch_snapshot() -> QuarterlySnapshot:
    snapshot = QualitySnapshotStore().get_latest_snapshot()
    if snapshot is None:
        raise HTTPException(status_code=404, detail="no quality snapshots generated yet")
    return snapshot


@router.get("/history", response_model=list[QualityWatchHistoryItem])
async def list_quality_watch_history() -> list[QualityWatchHistoryItem]:
    return QualitySnapshotStore().list_quarters()
