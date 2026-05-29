"""Compatibility alias for the Phase 12 v1 LLM advisor module."""
from backend.app.services.backtest.v1 import llm_search_space_advisor as _module
import sys as _sys

_sys.modules[__name__] = _module

