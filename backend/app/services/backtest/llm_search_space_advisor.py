"""Claude API client for closed-loop strategy parameter optimization.

Strict JSON-only responses. No verbose output. Token-minimal.

The advisor is given a compact summary and must return:
    {
      "action": "update_search_space" | "repair_patch" | "rollback" | "stop",
      "confidence": float,
      "next_search_space": {key: [values]},
      "weight_patch": {key: float},
      "stop": bool,
      "short_reason_codes": [string, max 5]
    }
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ─── System prompt (deliberately short to save tokens) ─────────────────────
_SYSTEM_PROMPT = """\
You are a quantitative strategy parameter advisor.
Analyze compact backtest summaries and return the next search-space patch.

CORE INVARIANTS (NEVER violate):
- 90-day high/low range must remain in [10%, 30%] zone (前期主力表態+回調洗浮盈 Bull Flag).
- Volume contraction during base period must remain enforced (max_volume_contraction_ratio <= 1.00).
- EMA(5/10/20) down→up transition must remain detected (min_ema_down_to_up_transition_score >= 30).
- EMA spread must remain tight (<= 0.08) to detect 糾結.

OUTPUT RULES:
- Strict JSON only. No markdown. No prose. No explanation outside JSON.
- Each parameter list 1~7 values. Stay within allowed bounds.
- risk_score weight must be <= 0.
- Prefer robust validation improvement over train-only performance.
- Do not shrink search_space too aggressively. Keep at least one exploration value per key.
- You never give trading advice. You never modify production rules directly.

SCHEMA:
{
  "action": "update_search_space" | "repair_patch" | "rollback" | "stop",
  "confidence": float 0~1,
  "next_search_space": {key: [v, ...]},
  "weight_patch": {key: float},
  "stop": bool,
  "short_reason_codes": [string, max 5]
}
"""


class AdvisorConfigError(RuntimeError):
    pass


class AdvisorAPIError(RuntimeError):
    pass


@dataclass
class AdvisorCallResult:
    raw_text: str
    input_tokens: int
    output_tokens: int
    model: str


class FakeAdvisor:
    """Mock advisor for --dry-run. Returns a no-op patch that keeps current space."""

    def __init__(self, model: str = "fake-model"):
        self.model = model
        self.call_count = 0

    def advise(self, compact_payload: dict) -> AdvisorCallResult:
        self.call_count += 1
        current_space = compact_payload.get("current_search_space", {})

        # Return current space unchanged with a stop signal after iteration 2 (smoke test)
        if compact_payload.get("iteration", 0) >= 2:
            response = {
                "action": "stop",
                "confidence": 0.5,
                "next_search_space": {},
                "weight_patch": {},
                "stop": True,
                "short_reason_codes": ["DRY_RUN_AUTO_STOP"],
            }
        else:
            response = {
                "action": "update_search_space",
                "confidence": 0.5,
                "next_search_space": dict(current_space),
                "weight_patch": {},
                "stop": False,
                "short_reason_codes": ["DRY_RUN_KEEP_SPACE"],
            }
        return AdvisorCallResult(
            raw_text=json.dumps(response),
            input_tokens=0,
            output_tokens=0,
            model=self.model,
        )


class ClaudeAdvisor:
    """Real Anthropic API client."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "claude-sonnet-4-6",
        temperature: float = 0.2,
        max_tokens: int = 1500,
        max_retries: int = 3,
        backoff_base: float = 1.0,
    ):
        try:
            import anthropic   # noqa: F401
        except ImportError as e:
            raise AdvisorConfigError(
                "anthropic SDK not installed. Run: pip install anthropic"
            ) from e

        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise AdvisorConfigError(
                "ANTHROPIC_API_KEY not set. Configure in backend/.env or environment."
            )
        # Defensive: never log/print key. Store inside SDK only.
        from anthropic import Anthropic
        self._client = Anthropic(api_key=key)
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.max_retries = max_retries
        self.backoff_base = backoff_base

    def _supports_temperature(self) -> bool:
        """Newer Claude models (opus-4-7+) deprecated the temperature parameter."""
        m = (self.model or "").lower()
        # Known: opus-4-7 rejects temperature. Conservative — skip for any opus-4-7+ / *-4-7+.
        if "opus-4-7" in m or "opus-4.7" in m:
            return False
        return True

    def advise(self, compact_payload: dict) -> AdvisorCallResult:
        """Call Claude API with retry. Raises AdvisorAPIError on permanent failure."""
        import anthropic

        user_content = json.dumps(compact_payload, ensure_ascii=False, default=str)
        last_err: Optional[Exception] = None

        for attempt in range(self.max_retries):
            try:
                create_kwargs = dict(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    system=_SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": user_content}],
                )
                if self._supports_temperature():
                    create_kwargs["temperature"] = self.temperature
                response = self._client.messages.create(**create_kwargs)
                # Extract first text block
                raw = ""
                for block in response.content:
                    if getattr(block, "type", None) == "text":
                        raw = block.text
                        break
                if not raw:
                    raise AdvisorAPIError("Empty response from Claude")

                return AdvisorCallResult(
                    raw_text=raw,
                    input_tokens=getattr(response.usage, "input_tokens", 0),
                    output_tokens=getattr(response.usage, "output_tokens", 0),
                    model=self.model,
                )

            except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as e:
                # Permanent — don't retry
                raise AdvisorAPIError(f"Auth/permission error: {type(e).__name__}") from e

            except anthropic.BadRequestError as e:
                # 400 — request shape is wrong; retrying won't help
                raise AdvisorAPIError(f"Bad request: {e}") from e

            except (
                anthropic.RateLimitError,
                anthropic.APIConnectionError,
                anthropic.APIStatusError,
                anthropic.APITimeoutError,
            ) as e:
                last_err = e
                if attempt < self.max_retries - 1:
                    sleep_s = self.backoff_base * (2 ** attempt)
                    logger.warning("transient API error (attempt %d): %s — retry in %.1fs",
                                   attempt + 1, type(e).__name__, sleep_s)
                    time.sleep(sleep_s)
                    continue

            except Exception as e:
                last_err = e
                if attempt < self.max_retries - 1:
                    time.sleep(self.backoff_base * (2 ** attempt))
                    continue

        raise AdvisorAPIError(f"Claude API failed after {self.max_retries} attempts: {last_err}")


def build_advisor(*, dry_run: bool, model: str, temperature: float) -> Any:
    """Factory — returns FakeAdvisor when dry_run, else ClaudeAdvisor."""
    if dry_run:
        return FakeAdvisor(model=model)
    return ClaudeAdvisor(model=model, temperature=temperature)
