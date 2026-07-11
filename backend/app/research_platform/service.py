from __future__ import annotations

import os
from datetime import datetime, timezone

from .budget import OpenAIBudgetGuard
from .catalog import inspect_crypto_sqlite
from .evidence import discover_legacy_experiments
from .repository import ResearchRepository
from .schemas import (
    ComponentHealth,
    DashboardOverview,
    FactorFinding,
    OrchestratorState,
    PaginatedExperiments,
    ServiceState,
    SystemStatusResponse,
    UniverseSnapshotResponse,
)
from .settings import ResearchSettings
from .universe import UniverseBuilder
from .validation import funding_ablation_finding, validation_gates


class ResearchPlatformService:
    def __init__(
        self,
        settings: ResearchSettings | None = None,
        repository: ResearchRepository | None = None,
    ) -> None:
        self.settings = settings or ResearchSettings.from_env()
        if self.settings.live_trading_enabled:
            raise RuntimeError("research platform refuses to start while LIVE_TRADING_ENABLED is true")
        self.repository = repository or ResearchRepository(self.settings.metadata_db_path)
        self.budget = OpenAIBudgetGuard(self.settings, self.repository)

    def refresh_local_evidence(self) -> tuple[int, int]:
        asset_count = 0
        asset = inspect_crypto_sqlite(self.settings.market_db_path)
        self.repository.upsert_asset(asset)
        asset_count += 1

        experiments = discover_legacy_experiments(self.settings.runs_path)
        for experiment in experiments:
            self.repository.upsert_experiment(experiment)
        self._seed_factor_findings(experiments)
        return asset_count, len(experiments)

    def ensure_bootstrapped(self) -> None:
        assets = self.repository.list_assets()
        experiments, _ = self.repository.list_experiments(limit=1, offset=0)
        if not assets or not experiments:
            self.refresh_local_evidence()

    def _seed_factor_findings(self, experiments) -> None:
        now = datetime.now(timezone.utc)
        experiment_ids = [item.experiment_id for item in experiments]
        findings = [
            funding_ablation_finding(experiments),
            FactorFinding(
                factor="OPEN_INTEREST",
                status="UNAVAILABLE",
                evidence_strength="NONE",
                applicable_scope="No historical OI coverage in the inspected cache",
                reason="Missing OI is null and blocks full-five-factor validation.",
                invalidation="Historical timestamped OI coverage passes data-quality checks.",
                observed_at=now,
            ),
            *[
                FactorFinding(
                    factor=factor,
                    status="INSUFFICIENT_EVIDENCE",
                    evidence_strength="LOW",
                    applicable_scope="Legacy baseline implementation",
                    reason=f"{factor} participates in existing rules, but a controlled marginal-value study is not available.",
                    invalidation=f"Ablation and walk-forward evidence shows {factor} adds no stable OOS value after costs.",
                    source_experiment_ids=experiment_ids,
                    observed_at=now,
                )
                for factor in ("EMA", "VOLUME", "RSI")
            ],
        ]
        for finding in findings:
            self.repository.upsert_factor_finding(finding)

    def system_status(self) -> SystemStatusResponse:
        now = datetime.now(timezone.utc)
        state, paused, updated_at = self.repository.system_state()
        assets = self.repository.list_assets()
        data_state = ServiceState.UNAVAILABLE
        data_detail = "No cataloged market data"
        if assets:
            latest = assets[0]
            data_state = ServiceState.DEGRADED if latest.is_stale or latest.warnings else ServiceState.HEALTHY
            data_detail = f"{sum(item.rows for item in latest.intervals):,} klines; tier={latest.data_tier.value}"
        warnings = []
        if not self.settings.api_token:
            warnings.append("Backend bearer token is not configured; mutation endpoints fail closed.")
        if not os.getenv("DATABASE_URL", "").strip():
            warnings.append("PostgreSQL is not configured; the local vertical slice uses SQLite metadata.")
        if not os.getenv("REDIS_URL", "").strip():
            warnings.append("Redis is not configured; distributed workers are not enabled.")
        return SystemStatusResponse(
            state=state,
            paused=paused,
            edge_status="NO ROBUST EDGE FOUND",
            live_trading_enabled=False,
            components=[
                ComponentHealth(name="api", state=ServiceState.HEALTHY, observed_at=now),
                ComponentHealth(name="market_data", state=data_state, observed_at=now, detail=data_detail),
                ComponentHealth(
                    name="postgresql",
                    state=ServiceState.NOT_CONFIGURED if not os.getenv("DATABASE_URL", "").strip() else ServiceState.NOT_VERIFIED,
                    observed_at=now,
                ),
                ComponentHealth(
                    name="redis",
                    state=ServiceState.NOT_CONFIGURED if not os.getenv("REDIS_URL", "").strip() else ServiceState.NOT_VERIFIED,
                    observed_at=now,
                ),
                ComponentHealth(
                    name="openai",
                    state=ServiceState.NOT_CONFIGURED if not os.getenv("OPENAI_API_KEY", "").strip() else ServiceState.NOT_VERIFIED,
                    observed_at=now,
                ),
            ],
            updated_at=updated_at,
            warnings=warnings,
        )

    def dashboard_overview(self) -> DashboardOverview:
        self.ensure_bootstrapped()
        assets = self.repository.list_assets()
        _, total = self.repository.list_experiments(limit=1, offset=0)
        candidates = self.repository.list_candidates()
        jobs = self.repository.job_counts()
        symbols = max(
            (item.symbols for asset in assets for item in asset.intervals),
            default=0,
        )
        warnings = [warning for asset in assets for warning in asset.warnings]
        return DashboardOverview(
            generated_at=datetime.now(timezone.utc),
            source="AI_STOCK_RESEARCH_METADATA",
            system=self.system_status(),
            data_assets=assets,
            symbols_scanned=symbols,
            experiments_completed=total,
            backtests_running=jobs.get("RUNNING", 0),
            queued_jobs=jobs.get("QUEUED", 0),
            best_candidate=candidates[0] if candidates else None,
            factor_findings=self.repository.list_factor_findings(),
            openai=self.budget.summary(),
            warnings=warnings,
        )

    def experiments(self, limit: int, offset: int) -> PaginatedExperiments:
        self.ensure_bootstrapped()
        items, total = self.repository.list_experiments(limit=limit, offset=offset)
        return PaginatedExperiments(items=items, total=total, limit=limit, offset=offset)

    def validation_gates(self):
        self.ensure_bootstrapped()
        items, _ = self.repository.list_experiments(limit=200, offset=0)
        return validation_gates(items)

    def current_universe(self) -> UniverseSnapshotResponse | None:
        return self.repository.latest_universe_snapshot()

    def refresh_universe(self, builder: UniverseBuilder | None = None) -> UniverseSnapshotResponse:
        snapshot = (builder or UniverseBuilder()).fetch_current()
        self.repository.save_universe_snapshot(snapshot)
        return snapshot

    def pause(self) -> tuple[OrchestratorState, datetime]:
        return self.repository.set_paused(True)

    def resume(self) -> tuple[OrchestratorState, datetime]:
        return self.repository.set_paused(False)
