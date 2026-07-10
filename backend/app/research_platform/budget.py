from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone

from .repository import ResearchRepository
from .schemas import OpenAIUsageSummary
from .settings import ResearchSettings


@dataclass(frozen=True)
class BudgetDecision:
    allowed: bool
    status: str
    reason: str


class OpenAIBudgetGuard:
    def __init__(self, settings: ResearchSettings, repository: ResearchRepository) -> None:
        self.settings = settings
        self.repository = repository

    def summary(self, now: datetime | None = None) -> OpenAIUsageSummary:
        now = now or datetime.now(timezone.utc)
        month = now.strftime("%Y-%m")
        usage = self.repository.openai_month_usage(month)
        cost = float(usage["cost_usd"])
        return OpenAIUsageSummary(
            month=month,
            automatic_calls=int(usage["automatic_calls"]),
            manual_calls=int(usage["manual_calls"]),
            total_calls=int(usage["total_calls"]),
            input_tokens=int(usage["input_tokens"]),
            output_tokens=int(usage["output_tokens"]),
            cost_usd=round(cost, 6),
            target_usd=self.settings.openai_monthly_target_usd,
            hard_stop_usd=self.settings.openai_monthly_hard_stop_usd,
            hard_stop_reached=cost >= self.settings.openai_monthly_hard_stop_usd,
            api_configured=bool(os.getenv("OPENAI_API_KEY", "").strip()),
            deferred_events=int(usage["deferred_events"]),
        )

    def authorize(self, kind: LiteralCallKind, estimated_worst_cost_usd: float) -> BudgetDecision:
        summary = self.summary()
        if not summary.api_configured:
            return BudgetDecision(False, "DEFERRED_NOT_CONFIGURED", "OPENAI_API_KEY is not configured")
        if estimated_worst_cost_usd < 0:
            return BudgetDecision(False, "DEFERRED_INVALID_ESTIMATE", "estimated cost cannot be negative")
        if summary.cost_usd + estimated_worst_cost_usd > summary.hard_stop_usd:
            return BudgetDecision(False, "DEFERRED_BUDGET_LIMIT", "estimated cost would exceed the monthly hard stop")
        if summary.total_calls >= self.settings.openai_total_calls_limit:
            return BudgetDecision(False, "DEFERRED_CALL_LIMIT", "monthly total call limit reached")
        if kind == "automatic" and summary.automatic_calls >= self.settings.openai_auto_calls_limit:
            return BudgetDecision(False, "DEFERRED_CALL_LIMIT", "monthly automatic call limit reached")
        if kind == "manual" and summary.manual_calls >= self.settings.openai_manual_calls_limit:
            return BudgetDecision(False, "DEFERRED_CALL_LIMIT", "monthly manual call limit reached")
        return BudgetDecision(True, "AUTHORIZED", "budget and call limits permit the event")


LiteralCallKind = str

