"""N pillar qualitative evidence analyzer.

The N pillar may only use structured sources that were already fetched by the
application, such as Yahoo/FinMind news, Taiwan news sentiment rows, and
calendar/announcement records. It does not fetch live data and it does not
invent catalysts.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from backend.app.services.strategy.canslim.screening_language import (
    clean_user_facing_text,
    contains_forbidden_action_language,
)


class NPillarClaim(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_url: str = Field(min_length=1)
    published_date: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    catalyst_type: str | None = None

    @model_validator(mode="after")
    def validate_claim_text(self) -> "NPillarClaim":
        if contains_forbidden_action_language(self.summary):
            raise ValueError("N pillar claim contains action/prediction language")
        return self


class NPillarAnalysis(BaseModel):
    model_config = ConfigDict(frozen=True)

    evidence: Literal["found", "not_found"]
    confidence: Literal["low", "moderate", "high"]
    summary: str
    claims: list[NPillarClaim] = Field(default_factory=list)
    data_warnings: list[str] = Field(default_factory=list)
    catalyst_score: int | None = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def validate_evidence_contract(self) -> "NPillarAnalysis":
        if contains_forbidden_action_language(self.summary) or contains_forbidden_action_language(self.data_warnings):
            raise ValueError("N pillar analysis contains action/prediction language")
        if self.evidence == "found" and not self.claims:
            raise ValueError("found evidence requires at least one sourced claim")
        if self.evidence == "not_found" and self.confidence != "low":
            raise ValueError("not_found evidence must have low confidence")
        if self.evidence == "not_found" and self.claims:
            raise ValueError("not_found evidence cannot include claims")
        return self


N_PILLAR_SYSTEM_PROMPT = """
You are a CANSLIM N-pillar evidence classifier. Use ONLY the provided JSON
sources. Every claim must cite source_url and published_date from an input row.
Do not invent catalysts. Do not include price targets, predictions, buy/sell/hold
language, or guaranteed outcomes. If no valid sourced evidence exists, return
evidence=not_found, confidence=low, catalyst_score=0, and no claims.

catalyst_score is an integer 0-100 grading how strong/material the NEW catalysts
are (new product, new orders/contracts, earnings surprise, M&A, capacity, etc.).
0 = no real catalyst (routine quotes/price chatter only); 100 = multiple strong,
recent, material catalysts. Base it ONLY on the provided sources.

Return ONLY a JSON object (no markdown, no commentary) with EXACTLY these fields:
{"evidence": "found" | "not_found",
 "confidence": "low" | "moderate" | "high",
 "catalyst_score": <integer 0-100>,
 "summary": "<one short factual sentence, no buy/sell/hold/target-price>",
 "claims": [{"source_url": "<copied verbatim from an input row>",
             "published_date": "<copied verbatim from that row>",
             "summary": "<short factual catalyst description>",
             "catalyst_type": "<new_product|new_order|earnings|m_and_a|capacity|other>"}],
 "data_warnings": []}
""".strip()


_GEMINI_SUMMARY_SYSTEM_PROMPT = """
You normalize Taiwan-stock news headlines into short factual catalyst notes for a
CANSLIM screener. You are given a JSON list of rows, each with source_url,
published_date and a raw title. For EACH row, write a one-line factual summary
based ONLY on what the title states — never add facts the title does not contain —
and tag a catalyst_type from: new_product, new_order, earnings, m_and_a, capacity,
other. Copy source_url and published_date verbatim. No buy/sell/hold language, no
price targets, no predictions. Drop nothing; return one item per input row.
""".strip()


class _NewsDigestItem(BaseModel):
    source_url: str = ""
    published_date: str = ""
    summary: str = ""
    catalyst_type: str | None = None


class _NewsDigest(BaseModel):
    items: list[_NewsDigestItem] = Field(default_factory=list)


async def _summarize_news_with_gemini(sources: list[dict]) -> "list[dict] | None":
    """Stage-1 agent: Gemini normalizes raw headlines into factual catalyst notes.

    Returns enriched source rows (source_url/published_date preserved, summary
    rewritten factually, catalyst_type tagged) intersected with the input urls so
    Gemini cannot introduce a source that was not provided. Returns None when
    GEMINI_API_KEY is absent / disabled / on any error (incl. 429), so the caller
    falls back to the raw rows."""
    if not sources:
        return None
    try:
        from backend.app.services.gemini_diagnostics import get_gemini_model, is_gemini_enabled, to_pydantic_ai_model_id
    except Exception:
        return None
    if not os.getenv("GEMINI_API_KEY") or not is_gemini_enabled():
        return None
    try:
        from pydantic_ai import Agent
    except Exception:
        return None
    source_by_url = {row["source_url"]: row for row in sources if row.get("source_url")}
    try:
        agent = Agent(
            to_pydantic_ai_model_id(get_gemini_model()),
            output_type=_NewsDigest,
            system_prompt=_GEMINI_SUMMARY_SYSTEM_PROMPT,
        )
        result = await agent.run(json.dumps(sources, ensure_ascii=False))
        digest = result.output
    except Exception:
        return None
    enriched: list[dict] = []
    for item in digest.items:
        base = source_by_url.get(item.source_url)
        if base is None:
            continue
        summary = _source_summary(item.summary or base["summary"])
        if contains_forbidden_action_language(summary):
            summary = base["summary"]
        enriched.append({
            "source_url": base["source_url"],
            "published_date": base["published_date"],
            "summary": summary,
            "catalyst_type": (item.catalyst_type or None),
        })
    return enriched or None


async def _call_claude_n_pillar(sources: list[dict]) -> "NPillarAnalysis | None":
    """Classify N-pillar catalysts with Claude (anthropic SDK). Returns None when no
    ANTHROPIC_API_KEY / SDK / on any error, so the caller falls back to deterministic."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        from anthropic import AsyncAnthropic
    except Exception:
        return None
    model = os.getenv("ANTHROPIC_FAST_MODEL") or "claude-haiku-4-5-20251001"
    try:
        client = AsyncAnthropic(api_key=api_key)
        resp = await client.messages.create(
            model=model,
            max_tokens=1024,
            system=N_PILLAR_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": json.dumps(sources, ensure_ascii=False)}],
        )
        text = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text")
        data = _parse_json_object(text)
        return NPillarAnalysis(**data) if isinstance(data, dict) else None
    except Exception:
        return None


def _parse_json_object(text: str) -> dict | None:
    s = (text or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s).strip()
    start, end = s.find("{"), s.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        obj = json.loads(s[start : end + 1])
    except (ValueError, TypeError):
        return None
    return obj if isinstance(obj, dict) else None


def analyze_n_pillar_sources(
    *,
    yahoo_news: list[dict[str, Any]] | None = None,
    tw_news_sentiment: list[dict[str, Any]] | None = None,
    calendar: list[dict[str, Any]] | dict[str, Any] | None = None,
    ai_output: NPillarAnalysis | dict[str, Any] | None = None,
) -> NPillarAnalysis:
    """Return strict N pillar evidence without fetching or hallucinating data.

    `ai_output` is injectable for tests or an external PydanticAI call. The
    returned claims are still intersected with valid input source rows, so a
    model cannot fabricate a claim or cite a source that was not provided.
    """

    valid_sources, warnings = _valid_source_rows(yahoo_news, tw_news_sentiment, calendar)
    source_keys = {(row["source_url"], row["published_date"]) for row in valid_sources}

    if not valid_sources:
        return NPillarAnalysis(
            evidence="not_found",
            confidence="low",
            summary="N pillar sourced evidence not found.",
            claims=[],
            data_warnings=warnings or ["N pillar source rows unavailable"],
        )

    if ai_output is not None:
        try:
            candidate = ai_output if isinstance(ai_output, NPillarAnalysis) else NPillarAnalysis(**ai_output)
            claims = [
                claim
                for claim in candidate.claims
                if (claim.source_url, claim.published_date) in source_keys
            ]
            if claims:
                return NPillarAnalysis(
                    evidence="found",
                    confidence=candidate.confidence,
                    summary=clean_user_facing_text(candidate.summary),
                    claims=claims,
                    data_warnings=warnings,
                    catalyst_score=candidate.catalyst_score,
                )
        except ValidationError:
            warnings.append("N pillar AI output rejected by source/language schema")

    claims = [_claim_from_source(row) for row in valid_sources[:8]]
    return NPillarAnalysis(
        evidence="found",
        confidence="moderate",
        summary=f"N pillar has {len(claims)} sourced qualitative item(s).",
        claims=claims,
        data_warnings=warnings,
    )


async def analyze_n_pillar_sources_with_ai(
    *,
    yahoo_news: list[dict[str, Any]] | None = None,
    tw_news_sentiment: list[dict[str, Any]] | None = None,
    calendar: list[dict[str, Any]] | dict[str, Any] | None = None,
) -> NPillarAnalysis:
    """Claude (anthropic) classification path; deterministic local analyzer is the
    fallback when ANTHROPIC_API_KEY / SDK is unavailable or the call fails."""

    valid_sources, _warnings = _valid_source_rows(yahoo_news, tw_news_sentiment, calendar)
    if not valid_sources:
        return analyze_n_pillar_sources(
            yahoo_news=yahoo_news,
            tw_news_sentiment=tw_news_sentiment,
            calendar=calendar,
        )
    # Stage 1 (Gemini): normalize headlines into factual catalyst notes. Falls back
    # to the raw rows when Gemini is unavailable/rate-limited. URLs/dates preserved.
    enriched = await _summarize_news_with_gemini(valid_sources)
    sources_for_ai = enriched or valid_sources
    # Stage 2 (Claude): classify evidence + grade catalyst_score. Claims are
    # re-intersected with the real source rows inside analyze_n_pillar_sources, so a
    # model cannot fabricate a source.
    ai_output = await _call_claude_n_pillar(sources_for_ai)
    return analyze_n_pillar_sources(
        yahoo_news=sources_for_ai,
        ai_output=ai_output,
    )


def _valid_source_rows(
    yahoo_news: list[dict[str, Any]] | None,
    tw_news_sentiment: list[dict[str, Any]] | None,
    calendar: list[dict[str, Any]] | dict[str, Any] | None,
) -> tuple[list[dict[str, str]], list[str]]:
    rows: list[dict[str, str]] = []
    warnings: list[str] = []
    for raw in [*(yahoo_news or []), *(tw_news_sentiment or []), *_calendar_rows(calendar)]:
        normalized = _normalize_source(raw)
        if normalized is None:
            if raw:
                warnings.append("N pillar source skipped because source_url or published_date was missing")
            continue
        rows.append(normalized)
    deduped: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        key = (row["source_url"], row["published_date"], row["summary"])
        if key not in seen:
            seen.add(key)
            deduped.append(row)
    return deduped, sorted(set(warnings))


def _calendar_rows(calendar: list[dict[str, Any]] | dict[str, Any] | None) -> list[dict[str, Any]]:
    if calendar is None:
        return []
    if isinstance(calendar, list):
        return calendar
    rows: list[dict[str, Any]] = []
    for value in calendar.values():
        if isinstance(value, list):
            rows.extend(item for item in value if isinstance(item, dict))
        elif isinstance(value, dict):
            rows.append(value)
    return rows


def _normalize_source(raw: dict[str, Any]) -> dict[str, str] | None:
    source_url = str(raw.get("source_url") or raw.get("url") or raw.get("link") or "").strip()
    published_date = str(
        raw.get("published_date")
        or raw.get("published_at")
        or raw.get("announcement_date")
        or raw.get("date")
        or ""
    ).strip()[:10]
    text = str(
        raw.get("summary")
        or raw.get("title")
        or raw.get("event")
        or raw.get("name")
        or raw.get("type")
        or ""
    ).strip()
    if not source_url or not published_date or not text:
        return None
    catalyst_type = raw.get("catalyst_type")
    return {
        "source_url": source_url,
        "published_date": published_date,
        "summary": _source_summary(text),
        "catalyst_type": str(catalyst_type) if catalyst_type else None,
    }


def _source_summary(text: str) -> str:
    cleaned = clean_user_facing_text(text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:220] or "Sourced qualitative item."


def _claim_from_source(row: dict[str, str]) -> NPillarClaim:
    return NPillarClaim(
        source_url=row["source_url"],
        published_date=row["published_date"],
        summary=row["summary"],
        catalyst_type=row.get("catalyst_type"),
    )
