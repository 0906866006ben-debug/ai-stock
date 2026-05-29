"""Compatibility alias for the Phase 12 v1 search-space validator module."""
from backend.app.services.backtest.v1 import search_space_validator as _module
import sys as _sys

_sys.modules[__name__] = _module
