from __future__ import annotations

import pytest

from backend.app.agents.retry import run_with_backoff


class _FakeAgent:
    def __init__(self, errors: list[Exception | None]):
        self._errors = errors
        self.calls = 0

    async def run(self, prompt):
        idx = self.calls
        self.calls += 1
        err = self._errors[idx]
        if err is not None:
            raise err
        return f"ok:{prompt}"


async def test_retries_transient_429_then_succeeds():
    agent = _FakeAgent([RuntimeError("429 RESOURCE_EXHAUSTED"), None])
    result = await run_with_backoff(agent, "p", base_delay=0)
    assert result == "ok:p"
    assert agent.calls == 2


async def test_non_retryable_raises_immediately():
    agent = _FakeAgent([ValueError("bad schema")])
    with pytest.raises(ValueError):
        await run_with_backoff(agent, "p", base_delay=0)
    assert agent.calls == 1


async def test_gives_up_after_max_attempts():
    agent = _FakeAgent([RuntimeError("429")] * 5)
    with pytest.raises(RuntimeError):
        await run_with_backoff(agent, "p", max_attempts=3, base_delay=0)
    assert agent.calls == 3
