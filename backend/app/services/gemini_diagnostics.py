"""Safe Gemini diagnostics helpers.

These helpers intentionally avoid logging full secrets.
"""

import os
from typing import Iterable

DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"


def mask_secret(value: str | None) -> str:
    """Return a short masked representation of a secret value."""
    if not value:
        return "<missing>"
    if len(value) <= 8:
        return "<masked>"
    return f"{value[:4]}...{value[-4:]}"


def get_gemini_diagnostics(
    model: str | None = None,
    fallback_models: Iterable[str] | None = None,
) -> dict:
    """Collect non-secret Gemini settings for logs or local diagnostics."""
    api_key = os.getenv("GEMINI_API_KEY")
    enabled_raw = os.getenv("GEMINI_ENABLED")
    configured_model = os.getenv("GEMINI_MODEL") or model or DEFAULT_GEMINI_MODEL
    fallback_list = list(fallback_models or get_gemini_fallback_models())

    return {
        "enabled": enabled_raw,
        "enabled_effective": is_gemini_enabled(),
        "api_key_loaded": bool(api_key),
        "masked_api_key": mask_secret(api_key),
        "model": configured_model,
        "fallback_models": fallback_list,
    }


def is_gemini_enabled() -> bool:
    """Return whether Gemini calls should be attempted."""
    enabled = os.getenv("GEMINI_ENABLED")
    if enabled is None:
        return True
    return enabled.strip().lower() not in {"0", "false", "no", "off"}


def get_gemini_model() -> str:
    """Return the configured primary Gemini model."""
    return os.getenv("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL


def get_gemini_fallback_models() -> list[str]:
    """Return configured fallback Gemini models."""
    configured = os.getenv("GEMINI_FALLBACK_MODELS")
    if not configured:
        return []
    return [item.strip() for item in configured.split(",") if item.strip()]


def get_gemini_model_chain() -> list[str]:
    """Return primary model plus unique fallback models."""
    models = [get_gemini_model(), *get_gemini_fallback_models()]
    unique_models = []
    for model in models:
        if model and model not in unique_models:
            unique_models.append(model)
    return unique_models


def to_pydantic_ai_model_id(model: str) -> str:
    """Return a provider-qualified model id for PydanticAI.

    Keep public config values unchanged (`gemini-...`) while avoiding
    PydanticAI's deprecated provider-less model syntax at the call site.
    """
    cleaned = str(model).strip()
    if ":" in cleaned:
        return cleaned
    if cleaned.startswith("gemini-"):
        return f"google-gla:{cleaned}"
    return cleaned


def log_gemini_diagnostics(
    *,
    context: str,
    model: str,
    attempted: bool,
    fallback_used: bool = False,
    error: Exception | None = None,
    fallback_models: Iterable[str] | None = None,
) -> None:
    """Print one safe diagnostic line for a Gemini call path."""
    diag = get_gemini_diagnostics(model=model, fallback_models=fallback_models)
    error_name = type(error).__name__ if error else None
    print(
        "[gemini-diagnostics] "
        f"context={context} "
        f"enabled={diag['enabled']} "
        f"enabled_effective={diag['enabled_effective']} "
        f"api_key_loaded={diag['api_key_loaded']} "
        f"api_key={diag['masked_api_key']} "
        f"model={diag['model']} "
        f"fallback_models={diag['fallback_models']} "
        f"attempted={attempted} "
        f"fallback_used={fallback_used} "
        f"error_type={error_name}"
    )
