from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.api.routes import research
from backend.app.main import app
from backend.app.research_platform.service import ResearchPlatformService

from .conftest import make_settings


def _client(
    tmp_path: Path,
    market_db: Path,
    runs_path: Path,
    token: str = "",
    require_read_auth: bool = False,
) -> TestClient:
    settings = make_settings(tmp_path, market_db, runs_path, token=token)
    if require_read_auth:
        settings = type(settings)(**{**settings.__dict__, "require_read_auth": True})
    service = ResearchPlatformService(settings=settings)
    app.dependency_overrides[research.get_research_service] = lambda: service
    return TestClient(app)


def test_overview_is_real_traceable_and_reports_no_edge(
    tmp_path: Path,
    market_db: Path,
    runs_path: Path,
) -> None:
    with _client(tmp_path, market_db, runs_path) as client:
        response = client.get("/api/v1/dashboard/overview")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["is_mock"] is False
    assert body["source"] == "AI_STOCK_RESEARCH_METADATA"
    assert body["generated_at"].endswith("Z")
    assert body["system"]["edge_status"] == "NO ROBUST EDGE FOUND"
    assert body["best_candidate"] is None
    assert body["experiments_completed"] == 1
    assert body["symbols_scanned"] == 2
    assert body["data_assets"][0]["oi_available"] is False
    assert {item["factor"] for item in body["factor_findings"]} == {
        "FUNDING", "OPEN_INTEREST", "EMA", "VOLUME", "RSI"
    }
    assert "api_token" not in str(body).lower()


def test_mutation_endpoint_fails_closed_without_token(
    tmp_path: Path,
    market_db: Path,
    runs_path: Path,
) -> None:
    with _client(tmp_path, market_db, runs_path) as client:
        response = client.post("/api/v1/system/pause")
    app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "RESEARCH_AUTH_NOT_CONFIGURED"


def test_validation_gate_endpoint_blocks_small_legacy_sample(
    tmp_path: Path,
    market_db: Path,
    runs_path: Path,
) -> None:
    with _client(tmp_path, market_db, runs_path) as client:
        response = client.get("/api/v1/research/validation-gates")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    gates = response.json()
    assert len(gates) == 4
    assert all(item["allowed"] is False for item in gates)
    assert all(item["observed_trades"] == 40 for item in gates)


def test_mutation_endpoint_requires_and_accepts_bearer_token(
    tmp_path: Path,
    market_db: Path,
    runs_path: Path,
) -> None:
    with _client(tmp_path, market_db, runs_path, token="test-secret") as client:
        denied = client.post("/api/v1/system/pause", headers={"Authorization": "Bearer wrong"})
        accepted = client.post(
            "/api/v1/system/pause",
            headers={"Authorization": "Bearer test-secret", "X-Request-ID": "request-123"},
        )
    app.dependency_overrides.clear()

    assert denied.status_code == 401
    assert accepted.status_code == 200
    assert accepted.json()["state"] == "PAUSED"
    assert accepted.json()["request_id"] == "request-123"


def test_production_read_auth_requires_bearer_token(
    tmp_path: Path,
    market_db: Path,
    runs_path: Path,
) -> None:
    with _client(tmp_path, market_db, runs_path, token="read-secret", require_read_auth=True) as client:
        denied = client.get("/api/v1/dashboard/overview")
        accepted = client.get(
            "/api/v1/dashboard/overview",
            headers={"Authorization": "Bearer read-secret"},
        )
    app.dependency_overrides.clear()

    assert denied.status_code == 401
    assert accepted.status_code == 200


def test_start_cycle_is_idempotent_within_hour(
    tmp_path: Path,
    market_db: Path,
    runs_path: Path,
) -> None:
    with _client(tmp_path, market_db, runs_path, token="cycle-secret") as client:
        headers = {"Authorization": "Bearer cycle-secret"}
        first = client.post("/api/v1/research/start-cycle", headers=headers)
        second = client.post("/api/v1/research/start-cycle", headers=headers)
        jobs = client.get("/api/v1/jobs")
    app.dependency_overrides.clear()

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["job_ids"] == second.json()["job_ids"]
    assert len(jobs.json()) == 2
    assert "No locked test or trading job" in first.json()["message"]
