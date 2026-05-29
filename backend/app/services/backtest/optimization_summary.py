"""Compatibility alias for the Phase 12 v1 optimization summary module."""
from backend.app.services.backtest.v1 import optimization_summary as _module
import sys as _sys

_sys.modules[__name__] = _module

