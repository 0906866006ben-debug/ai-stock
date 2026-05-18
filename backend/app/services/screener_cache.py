from __future__ import annotations

import json
import time
from threading import Lock
from typing import Any, Optional

from backend.app.models.screener_schemas import ScreenerResponse
from backend.app.services.screener_rules import load_surge_candidate_rules, require_rule


_cache: dict[str, tuple[float, ScreenerResponse]] = {}
_force_refresh_at: dict[str, float] = {}
_lock = Lock()


class ForceRefreshRateLimited(RuntimeError):
    pass


def make_cache_key(params: dict[str, Any]) -> str:
    return json.dumps(params, sort_keys=True, ensure_ascii=False, default=str)


def get_cached_response(cache_key: str) -> Optional[ScreenerResponse]:
    rules = load_surge_candidate_rules()
    ttl_seconds = int(require_rule(rules, "cache.ttl_seconds"))
    now = time.time()
    with _lock:
        cached = _cache.get(cache_key)
        if not cached:
            return None
        cached_at, response = cached
        if now - cached_at > ttl_seconds:
            _cache.pop(cache_key, None)
            return None
        return response


def set_cached_response(cache_key: str, response: ScreenerResponse) -> None:
    with _lock:
        _cache[cache_key] = (time.time(), response)


def check_force_refresh_allowed(cache_key: str) -> None:
    rules = load_surge_candidate_rules()
    cooldown_seconds = int(require_rule(rules, "cache.force_refresh_cooldown_seconds"))
    now = time.time()
    with _lock:
        last_refresh = _force_refresh_at.get(cache_key)
        if last_refresh is not None and now - last_refresh < cooldown_seconds:
            raise ForceRefreshRateLimited("force_refresh is limited to once every 5 minutes per parameter set.")
        _force_refresh_at[cache_key] = now
