"""Strict JSON validator for Claude API responses in the auto-optimize loop.

Validation pipeline:
  1) JSON parse
  2) Schema check (action / confidence / fields presence)
  3) action whitelist
  4) Per-key whitelist
  5) Allowed bounds + core invariants
  6) List size constraints
  7) Weight bounds + risk_score non-positive
  8) Sum-of-positive-weights sanity check

On partial failure, invalid keys are dropped (not crash). On total failure, the
caller can fall back to previous search_space or trigger repair mode.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

logger = logging.getLogger(__name__)


ALLOWED_ACTIONS = {"update_search_space", "repair_patch", "rollback", "stop"}
MAX_LIST_LEN = 7
MIN_LIST_LEN = 1


@dataclass
class ClaudeResponse:
    action: str
    confidence: float
    next_search_space: dict[str, list[float]]
    weight_patch: dict[str, float]
    stop: bool
    short_reason_codes: list[str]
    raw_text: str = ""


@dataclass
class ValidationResult:
    valid: bool
    cleaned: Optional[ClaudeResponse]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    requires_repair: bool = False
    dropped_keys: list[str] = field(default_factory=list)


def load_bounds_config(path: Path | str) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    required = ["core_invariants", "parameter_mapping", "allowed_bounds",
                "weight_whitelist", "weight_bounds"]
    missing = [k for k in required if k not in cfg]
    if missing:
        raise ValueError(f"allowed_bounds.yaml missing keys: {missing}")
    return cfg


def parse_response(raw_text: str) -> Optional[dict]:
    """Robust JSON extraction: tolerate leading/trailing whitespace, code fences."""
    text = raw_text.strip()
    # Strip markdown fences if present (defensive, system prompt forbids them)
    if text.startswith("```"):
        lines = text.split("\n")
        # Drop first and last fence lines
        text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
    text = text.strip()

    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting first JSON object substring
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None


def validate(raw_text: str, bounds_config: dict[str, Any]) -> ValidationResult:
    """Top-level validation. Returns ValidationResult with cleaned ClaudeResponse on success."""
    result = ValidationResult(valid=False, cleaned=None)

    parsed = parse_response(raw_text)
    if parsed is None:
        result.errors.append("JSON parse failure")
        result.requires_repair = True
        return result

    # ── Schema ────────────────────────────────────────────────────────────
    required_fields = ["action", "confidence", "next_search_space",
                       "weight_patch", "stop", "short_reason_codes"]
    missing = [f for f in required_fields if f not in parsed]
    if missing:
        result.errors.append(f"Missing required fields: {missing}")
        result.requires_repair = True
        return result

    action = str(parsed.get("action", "")).strip()
    if action not in ALLOWED_ACTIONS:
        result.errors.append(f"Invalid action: {action}")
        result.requires_repair = True
        return result

    try:
        confidence = float(parsed["confidence"])
    except (TypeError, ValueError):
        result.warnings.append("Invalid confidence; defaulting to 0.5")
        confidence = 0.5
    confidence = max(0.0, min(1.0, confidence))

    if not isinstance(parsed.get("next_search_space"), dict):
        result.errors.append("next_search_space must be dict")
        result.requires_repair = True
        return result

    if not isinstance(parsed.get("weight_patch"), dict):
        result.errors.append("weight_patch must be dict")
        result.requires_repair = True
        return result

    short_reason = parsed.get("short_reason_codes", [])
    if not isinstance(short_reason, list):
        short_reason = []
        result.warnings.append("short_reason_codes was not a list; coerced to []")
    short_reason = [str(c).strip()[:50] for c in short_reason][:5]

    # ── next_search_space key/value validation ────────────────────────────
    cleaned_space: dict[str, list[float]] = {}
    allowed_params = bounds_config.get("allowed_bounds", {})
    core_invariants = bounds_config.get("core_invariants", {}).get("constraints", {})
    parameter_mapping = bounds_config.get("parameter_mapping", {})

    for key, values in parsed["next_search_space"].items():
        key = str(key).strip()
        if key not in allowed_params and key not in parameter_mapping.values():
            result.dropped_keys.append(key)
            result.warnings.append(f"non-whitelisted key dropped: {key}")
            continue

        if not isinstance(values, list) or len(values) < MIN_LIST_LEN:
            result.dropped_keys.append(key)
            result.warnings.append(f"key {key}: list empty or invalid, dropped")
            continue

        # Truncate to max length
        if len(values) > MAX_LIST_LEN:
            values = values[:MAX_LIST_LEN]
            result.warnings.append(f"key {key}: truncated to {MAX_LIST_LEN} values")

        # Apply bounds: core_invariants take precedence
        invariant = core_invariants.get(key)
        bounds = allowed_params.get(key, [-1e9, 1e9])
        if invariant:
            lo = max(bounds[0], invariant.get("hard_min", bounds[0]))
            hi = min(bounds[1], invariant.get("hard_max", bounds[1]))
        else:
            lo, hi = bounds[0], bounds[1]

        clean_vals: list[float] = []
        out_of_bounds: list[float] = []
        for v in values:
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            if lo <= fv <= hi:
                clean_vals.append(fv)
            else:
                out_of_bounds.append(fv)

        if out_of_bounds:
            result.warnings.append(f"key {key}: dropped out-of-bounds values {out_of_bounds} (allowed [{lo},{hi}])")

        if len(clean_vals) < MIN_LIST_LEN:
            result.dropped_keys.append(key)
            result.warnings.append(f"key {key}: no in-bounds values, dropped")
            continue

        # Dedup & sort for stability
        clean_vals = sorted(set(clean_vals))
        cleaned_space[key] = clean_vals

    # ── weight_patch validation ───────────────────────────────────────────
    cleaned_weights: dict[str, float] = {}
    weight_whitelist = set(bounds_config.get("weight_whitelist", []))
    weight_bounds = bounds_config.get("weight_bounds", {})

    for key, value in parsed["weight_patch"].items():
        key = str(key).strip()
        if key not in weight_whitelist:
            result.warnings.append(f"weight key dropped (not whitelisted): {key}")
            continue
        try:
            fv = float(value)
        except (TypeError, ValueError):
            result.warnings.append(f"weight {key} not numeric, dropped")
            continue

        # risk_score must be non-positive
        if key == "risk_score" and fv > 0:
            result.warnings.append(f"weight risk_score={fv} > 0 rejected; must be <= 0")
            continue

        # Bounds
        b = weight_bounds.get(key, [-1.0, 1.0])
        if not (b[0] <= fv <= b[1]):
            result.warnings.append(f"weight {key}={fv} out of bounds {b}; dropped")
            continue

        cleaned_weights[key] = fv

    # Sum-of-positive sanity check
    if cleaned_weights:
        pos_sum = sum(v for v in cleaned_weights.values() if v > 0)
        if not (0.7 <= pos_sum <= 1.3):
            result.warnings.append(
                f"sum of positive weights {pos_sum:.2f} outside [0.7, 1.3]; may need rebalancing"
            )

    # ── Final assembly ────────────────────────────────────────────────────
    is_stop_action = action == "stop" or bool(parsed.get("stop"))

    # update_search_space / repair_patch must produce at least 1 key (unless stop)
    if action in {"update_search_space", "repair_patch"} and not cleaned_space and not is_stop_action:
        result.errors.append(f"action={action} but no valid keys after validation")
        result.requires_repair = True
        return result

    result.cleaned = ClaudeResponse(
        action=action,
        confidence=confidence,
        next_search_space=cleaned_space,
        weight_patch=cleaned_weights,
        stop=is_stop_action,
        short_reason_codes=short_reason,
        raw_text=raw_text,
    )
    result.valid = True
    return result


# ────────────────────────────────────────────────────────────────────────────
# Helpers used by optimization_loop
# ────────────────────────────────────────────────────────────────────────────

def to_rules_dotted_paths(short_keys_dict: dict[str, list], parameter_mapping: dict) -> dict[str, list]:
    """{short_key: [v,...]} → {dotted.path: [v,...]} for the optimizer.

    Keys already in dotted form (e.g. price_position.min_return_60d) are passed through.
    """
    out: dict[str, list] = {}
    for k, v in short_keys_dict.items():
        out[parameter_mapping.get(k, k)] = v
    return out


def weight_patch_to_overrides(weight_patch: dict[str, float]) -> dict[str, list[float]]:
    """Weight patch → search-space entries under scoring.pre_breakout_weights.*

    Each weight becomes a single-element list so the random sampler picks it.
    """
    return {f"scoring.pre_breakout_weights.{k}": [v] for k, v in weight_patch.items()}
