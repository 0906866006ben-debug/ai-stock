from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .schemas import (
    CandidateSummary,
    DataAssetSummary,
    ExperimentSummary,
    FactorFinding,
    JobSummary,
    OrchestratorState,
    UniverseSnapshotResponse,
    WorkerHeartbeat,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _json(model: Any) -> str:
    if hasattr(model, "model_dump_json"):
        return model.model_dump_json()
    return json.dumps(model, separators=(",", ":"), sort_keys=True)


class ResearchRepository:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _migrate(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS research_schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS research_system_state (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    state TEXT NOT NULL,
                    paused INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS research_data_assets (
                    asset_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS research_experiments (
                    experiment_id TEXT PRIMARY KEY,
                    period_start TEXT,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS research_factor_findings (
                    factor TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS research_candidates (
                    strategy_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS research_universe_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    observed_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS research_jobs (
                    job_id TEXT PRIMARY KEY,
                    dedupe_key TEXT NOT NULL UNIQUE,
                    job_type TEXT NOT NULL,
                    state TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    heartbeat_at TEXT
                );
                CREATE TABLE IF NOT EXISTS research_openai_usage (
                    usage_id TEXT PRIMARY KEY,
                    occurred_at TEXT NOT NULL,
                    call_kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    model TEXT NOT NULL,
                    input_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    cost_usd REAL NOT NULL DEFAULT 0,
                    event_key TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS research_worker_heartbeats (
                    worker_id TEXT PRIMARY KEY,
                    worker_type TEXT NOT NULL,
                    state TEXT NOT NULL,
                    current_job_id TEXT,
                    process_id INTEGER NOT NULL,
                    started_at TEXT NOT NULL,
                    heartbeat_at TEXT NOT NULL
                );
                """
            )
            now = utc_now().isoformat()
            conn.execute(
                "INSERT OR IGNORE INTO research_schema_migrations(version, applied_at) VALUES(1, ?)",
                (now,),
            )
            conn.execute(
                "INSERT OR IGNORE INTO research_system_state(singleton, state, paused, updated_at) "
                "VALUES(1, ?, 0, ?)",
                (OrchestratorState.IDLE.value, now),
            )

    def upsert_asset(self, asset: DataAssetSummary) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO research_data_assets(asset_id, payload_json, updated_at) VALUES(?,?,?) "
                "ON CONFLICT(asset_id) DO UPDATE SET payload_json=excluded.payload_json, updated_at=excluded.updated_at",
                (asset.asset_id, _json(asset), utc_now().isoformat()),
            )

    def list_assets(self) -> list[DataAssetSummary]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM research_data_assets ORDER BY updated_at DESC"
            ).fetchall()
        return [DataAssetSummary.model_validate_json(row[0]) for row in rows]

    def upsert_experiment(self, experiment: ExperimentSummary) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO research_experiments(experiment_id, period_start, payload_json, updated_at) "
                "VALUES(?,?,?,?) ON CONFLICT(experiment_id) DO UPDATE SET "
                "period_start=excluded.period_start, payload_json=excluded.payload_json, updated_at=excluded.updated_at",
                (
                    experiment.experiment_id,
                    experiment.period_start.isoformat() if experiment.period_start else None,
                    _json(experiment),
                    utc_now().isoformat(),
                ),
            )

    def list_experiments(self, limit: int = 50, offset: int = 0) -> tuple[list[ExperimentSummary], int]:
        with self._connect() as conn:
            total = int(conn.execute("SELECT COUNT(*) FROM research_experiments").fetchone()[0])
            rows = conn.execute(
                  "SELECT payload_json FROM research_experiments ORDER BY period_start DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [ExperimentSummary.model_validate_json(row[0]) for row in rows], total

    def upsert_factor_finding(self, finding: FactorFinding) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO research_factor_findings(factor, payload_json, updated_at) VALUES(?,?,?) "
                "ON CONFLICT(factor) DO UPDATE SET payload_json=excluded.payload_json, updated_at=excluded.updated_at",
                (finding.factor, _json(finding), utc_now().isoformat()),
            )

    def list_factor_findings(self) -> list[FactorFinding]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM research_factor_findings ORDER BY factor"
            ).fetchall()
        return [FactorFinding.model_validate_json(row[0]) for row in rows]

    def list_candidates(self) -> list[CandidateSummary]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM research_candidates ORDER BY updated_at DESC"
            ).fetchall()
        return [CandidateSummary.model_validate_json(row[0]) for row in rows]

    def save_universe_snapshot(self, snapshot: UniverseSnapshotResponse) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO research_universe_snapshots(snapshot_id, observed_at, payload_json) VALUES(?,?,?) "
                "ON CONFLICT(snapshot_id) DO UPDATE SET observed_at=excluded.observed_at, payload_json=excluded.payload_json",
                (snapshot.snapshot_id, snapshot.observed_at.isoformat(), _json(snapshot)),
            )

    def latest_universe_snapshot(self) -> UniverseSnapshotResponse | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM research_universe_snapshots ORDER BY observed_at DESC LIMIT 1"
            ).fetchone()
        return UniverseSnapshotResponse.model_validate_json(row[0]) if row else None

    def system_state(self) -> tuple[OrchestratorState, bool, datetime]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT state, paused, updated_at FROM research_system_state WHERE singleton=1"
            ).fetchone()
        return OrchestratorState(row[0]), bool(row[1]), datetime.fromisoformat(row[2])

    def set_paused(self, paused: bool) -> tuple[OrchestratorState, datetime]:
        state = OrchestratorState.PAUSED if paused else OrchestratorState.IDLE
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                "UPDATE research_system_state SET state=?, paused=?, updated_at=? WHERE singleton=1",
                (state.value, int(paused), now.isoformat()),
            )
        return state, now

    def enqueue_job(self, job_type: str, dedupe_key: str, priority: int, payload: dict[str, Any]) -> str:
        now = utc_now().isoformat()
        job_id = str(uuid.uuid4())
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO research_jobs(job_id,dedupe_key,job_type,state,priority,payload_json,created_at,updated_at) "
                "VALUES(?,?,?,'QUEUED',?,?,?,?)",
                (job_id, dedupe_key, job_type, priority, _json(payload), now, now),
            )
            row = conn.execute(
                "SELECT job_id FROM research_jobs WHERE dedupe_key=?", (dedupe_key,)
            ).fetchone()
        return str(row[0])

    def claim_next_job(self) -> JobSummary | None:
        now = utc_now().isoformat()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM research_jobs WHERE state IN ('QUEUED','RETRY') "
                "ORDER BY priority ASC, created_at ASC LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE research_jobs SET state='RUNNING', attempts=attempts+1, heartbeat_at=?, updated_at=? "
                "WHERE job_id=? AND state IN ('QUEUED','RETRY')",
                (now, now, row["job_id"]),
            )
            claimed = conn.execute(
                "SELECT * FROM research_jobs WHERE job_id=?", (row["job_id"],)
            ).fetchone()
        return self._job_from_row(claimed)

    def heartbeat_job(self, job_id: str) -> None:
        now = utc_now().isoformat()
        with self._connect() as conn:
            conn.execute(
                "UPDATE research_jobs SET heartbeat_at=?, updated_at=? WHERE job_id=? AND state='RUNNING'",
                (now, now, job_id),
            )

    def finish_job(self, job_id: str, *, success: bool, error: str | None = None, max_attempts: int = 3) -> None:
        now = utc_now().isoformat()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT attempts,payload_json FROM research_jobs WHERE job_id=?", (job_id,)
            ).fetchone()
            if row is None:
                return
            payload = json.loads(row["payload_json"])
            if error:
                payload["last_error"] = error[:500]
            state = "COMPLETED" if success else ("RETRY" if int(row["attempts"]) < max_attempts else "FAILED")
            conn.execute(
                "UPDATE research_jobs SET state=?, payload_json=?, heartbeat_at=NULL, updated_at=? WHERE job_id=?",
                (state, _json(payload), now, job_id),
            )

    def recover_stale_jobs(self, stale_before: datetime) -> int:
        now = utc_now().isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE research_jobs SET state='RETRY', heartbeat_at=NULL, updated_at=? "
                "WHERE state='RUNNING' AND heartbeat_at < ?",
                (now, stale_before.astimezone(timezone.utc).isoformat()),
            )
        return int(cursor.rowcount)

    def list_jobs(self, limit: int = 100) -> list[JobSummary]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM research_jobs ORDER BY priority ASC, created_at ASC LIMIT ?", (limit,)
            ).fetchall()
        return [self._job_from_row(row) for row in rows]

    @staticmethod
    def _job_from_row(row: sqlite3.Row) -> JobSummary:
        return JobSummary(
            job_id=row["job_id"],
            job_type=row["job_type"],
            state=row["state"],
            priority=row["priority"],
            attempts=row["attempts"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            payload=json.loads(row["payload_json"]),
        )

    def record_worker_heartbeat(self, heartbeat: WorkerHeartbeat) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO research_worker_heartbeats(worker_id,worker_type,state,current_job_id,process_id,started_at,heartbeat_at) "
                "VALUES(?,?,?,?,?,?,?) ON CONFLICT(worker_id) DO UPDATE SET worker_type=excluded.worker_type, "
                "state=excluded.state,current_job_id=excluded.current_job_id,process_id=excluded.process_id,heartbeat_at=excluded.heartbeat_at",
                (
                    heartbeat.worker_id,
                    heartbeat.worker_type,
                    heartbeat.state,
                    heartbeat.current_job_id,
                    heartbeat.process_id,
                    heartbeat.started_at.isoformat(),
                    heartbeat.heartbeat_at.isoformat(),
                ),
            )

    def list_workers(self) -> list[WorkerHeartbeat]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM research_worker_heartbeats ORDER BY worker_id"
            ).fetchall()
        return [
            WorkerHeartbeat(
                worker_id=row["worker_id"],
                worker_type=row["worker_type"],
                state=row["state"],
                current_job_id=row["current_job_id"],
                process_id=row["process_id"],
                started_at=datetime.fromisoformat(row["started_at"]),
                heartbeat_at=datetime.fromisoformat(row["heartbeat_at"]),
            )
            for row in rows
        ]

    def job_counts(self) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute("SELECT state, COUNT(*) FROM research_jobs GROUP BY state").fetchall()
        return {str(row[0]): int(row[1]) for row in rows}

    def openai_month_usage(self, month_prefix: str) -> dict[str, float | int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT call_kind,status,input_tokens,output_tokens,cost_usd FROM research_openai_usage "
                "WHERE substr(occurred_at,1,7)=?",
                (month_prefix,),
            ).fetchall()
        return {
            "automatic_calls": sum(1 for row in rows if row[0] == "automatic" and row[1] == "COMPLETED"),
            "manual_calls": sum(1 for row in rows if row[0] == "manual" and row[1] == "COMPLETED"),
            "total_calls": sum(1 for row in rows if row[1] == "COMPLETED"),
            "input_tokens": sum(int(row[2]) for row in rows),
            "output_tokens": sum(int(row[3]) for row in rows),
            "cost_usd": sum(float(row[4]) for row in rows),
            "deferred_events": sum(1 for row in rows if row[1].startswith("DEFERRED")),
        }
