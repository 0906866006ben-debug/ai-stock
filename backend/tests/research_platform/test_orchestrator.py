from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.app.research_platform.orchestrator import ResearchOrchestrator
from backend.app.research_platform.repository import ResearchRepository


class FakeService:
    def __init__(self, repository: ResearchRepository) -> None:
        self.repository = repository
        self.calls: list[str] = []

    def refresh_local_evidence(self) -> None:
        self.calls.append("local")

    def refresh_universe(self) -> None:
        self.calls.append("universe")


def test_cycle_is_idempotent_and_jobs_complete_in_priority_order(tmp_path: Path) -> None:
    repository = ResearchRepository(tmp_path / "research.db")
    service = FakeService(repository)
    orchestrator = ResearchOrchestrator(service=service, worker_id="worker-test")

    first_ids = orchestrator.schedule_cycle("cycle:one")
    second_ids = orchestrator.schedule_cycle("cycle:one")

    assert first_ids == second_ids
    assert len(repository.list_jobs()) == 2
    assert orchestrator.run_once() is True
    assert service.calls == ["local"]
    assert repository.list_jobs()[0].state == "COMPLETED"
    assert orchestrator.run_once() is True
    assert service.calls == ["local", "universe"]
    assert {job.state for job in repository.list_jobs()} == {"COMPLETED"}
    assert repository.list_workers()[0].state == "IDLE"


def test_pause_prevents_claiming_jobs(tmp_path: Path) -> None:
    repository = ResearchRepository(tmp_path / "research.db")
    service = FakeService(repository)
    orchestrator = ResearchOrchestrator(service=service, worker_id="worker-paused")
    orchestrator.schedule_cycle("cycle:paused")
    repository.set_paused(True)

    assert orchestrator.run_once() is False
    assert not service.calls
    assert {job.state for job in repository.list_jobs()} == {"QUEUED"}


def test_stale_running_job_is_recovered(tmp_path: Path) -> None:
    repository = ResearchRepository(tmp_path / "research.db")
    repository.enqueue_job("REFRESH_LOCAL_EVIDENCE", "stale-job", 0, {})
    claimed = repository.claim_next_job()
    assert claimed is not None
    stale = datetime.now(timezone.utc) - timedelta(hours=1)
    with repository._connect() as conn:
        conn.execute(
            "UPDATE research_jobs SET heartbeat_at=? WHERE job_id=?",
            (stale.isoformat(), claimed.job_id),
        )

    recovered = repository.recover_stale_jobs(datetime.now(timezone.utc) - timedelta(minutes=10))

    assert recovered == 1
    assert repository.list_jobs()[0].state == "RETRY"

