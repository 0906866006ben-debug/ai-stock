import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


RULES_PATH = Path(__file__).resolve().parents[2] / "technical_analyzer" / "v1" / "registry" / "rules_v1.yaml"

# Environment variable for runtime override (used by parameter optimizer).
# When set, this YAML path is used instead of RULES_PATH. Caller is responsible
# for invoking `load_surge_candidate_rules.cache_clear()` after changing the env var.
_OVERRIDE_ENV_VAR = "RULES_V1_YAML_PATH"


class ScreenerRulesError(RuntimeError):
    pass


def _effective_rules_path() -> Path:
    override = os.environ.get(_OVERRIDE_ENV_VAR)
    if override:
        path = Path(override)
        if not path.exists():
            raise ScreenerRulesError(f"Override rules file not found: {path}")
        return path
    return RULES_PATH


@lru_cache(maxsize=1)
def load_surge_candidate_rules() -> dict[str, Any]:
    path = _effective_rules_path()
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    rules = payload.get("surge_candidate")
    if not isinstance(rules, dict):
        raise ScreenerRulesError("Missing surge_candidate section in rules YAML.")
    return rules


def require_rule(rules: dict[str, Any], dotted_path: str) -> Any:
    current: Any = rules
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise ScreenerRulesError(f"Missing surge_candidate rule: {dotted_path}")
        current = current[part]
    return current
