from __future__ import annotations

import os
import socket
import uuid
from datetime import datetime, timedelta, timezone
from threading import Event

from .schemas import WorkerHeartbeat
from .service import ResearchPlatformService


class ResearchOrchestrator:
    def __init__(self, service: ResearchPlatformService | None = None, worker_id: str | None = None) -> None:
        self.service = service or ResearchPlatformService()
        self.repository = self.service.repository
        self.worker_id = worker_id or f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        self.started_at = datetime.now(timezone.utc)

    def schedule_cycle(self, cycle_key: str) -> list[str]:
        return [
            self.repository.enqueue_job(
                "REFRESH_LOCAL_EVIDENCE",
                f"{cycle_key}:local-evidence",
                0,
                {"cycle_key": cycle_key, "source": "scheduled-cycle"},
            ),
            self.repository.enqueue_job(
                "REFRESH_UNIVERSE",
                f"{cycle_key}:universe",
                1,
                {"cycle_key": cycle_key, "source": "scheduled-cycle"},
            ),
        ]

    def heartbeat(self, state: str, current_job_id: str | None = None) -> None:
        self.repository.record_worker_heartbeat(
            WorkerHeartbeat(
                worker_id=self.worker_id,
                worker_type="RESEARCH_ORCHESTRATOR",
                state=state,
                current_job_id=current_job_id,
                process_id=os.getpid(),
                started_at=self.started_at,
                heartbeat_at=datetime.now(timezone.utc),
            )
        )

    def run_once(self) -> bool:
        state, paused, _ = self.repository.system_state()
        if paused:
            self.heartbeat(state.value)
            return False
        self.repository.recover_stale_jobs(datetime.now(timezone.utc) - timedelta(minutes=10))
        job = self.repository.claim_next_job()
        if job is None:
            self.heartbeat("IDLE")
            return False

        self.heartbeat("RUNNING", job.job_id)
        try:
            if job.job_type == "REFRESH_LOCAL_EVIDENCE":
                self.service.refresh_local_evidence()
            elif job.job_type == "REFRESH_UNIVERSE":
                self.service.refresh_universe()
            else:
                raise ValueError(f"unsupported research job type: {job.job_type}")
        except Exception as exc:
            self.repository.finish_job(job.job_id, success=False, error=f"{type(exc).__name__}: {exc}")
        else:
            self.repository.finish_job(job.job_id, success=True)
        finally:
            self.heartbeat("IDLE")
        return True

    def run_forever(self, stop: Event, poll_seconds: float = 5.0) -> None:
        self.heartbeat("STARTING")
        while not stop.is_set():
            worked = self.run_once()
            if not worked:
                stop.wait(max(poll_seconds, 0.25))
        self.heartbeat("STOPPED")

