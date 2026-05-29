"""Shared retry/backoff for PydanticAI Gemini agent calls.

Gemini free tier returns 429 (rate limit) and occasionally 503 under load. These
are transient, so retry with exponential backoff before letting the caller fall
back to its mock path. Non-retryable errors propagate immediately.
"""
from __future__ import annotations

import asyncio
from typing import Any

_RETRYABLE_MARKERS = (
    "429",
    "resource_exhausted",
    "rate limit",
    "too many requests",
    "503",
    "service unavailable",
    "unavailable",
    "overloaded",
)


def _is_retryable(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None)
    if status in (429, 503):
        return True
    text = str(exc).lower()
    return any(marker in text for marker in _RETRYABLE_MARKERS)


async def run_with_backoff(
    agent: Any,
    prompt: Any,
    *,
    max_attempts: int = 3,
    base_delay: float = 2.0,
) -> Any:
    """Call ``agent.run(prompt)`` retrying transient 429/503 with backoff.

    Re-raises the last exception when attempts are exhausted or the error is not
    retryable, so each agent's existing try/except still degrades to mock data.
    """
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            return await agent.run(prompt)
        except Exception as exc:  # noqa: BLE001 - classified below, then re-raised
            last_exc = exc
            if attempt == max_attempts - 1 or not _is_retryable(exc):
                raise
            await asyncio.sleep(base_delay * (2 ** attempt))
    assert last_exc is not None
    raise last_exc
