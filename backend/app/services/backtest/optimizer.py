"""Compatibility alias for the Phase 12 v1 optimizer module."""
from backend.app.services.backtest.v1 import optimizer as _module
import sys as _sys

_sys.modules[__name__] = _module

