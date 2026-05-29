# Optimization Rewrite Cleanup

Date: 2026-05-20

## Scope

This cleanup only touched surge-candidate backtest / optimization files and outputs. It did not reorganize unrelated frontend, stock-analysis agent, or API modules.

## Archived

Old optimization outputs and historical backtest reports were moved to:

```text
artifacts/_archive/optimization_legacy_20260520/
```

Archived folders:

- `backtest_history/`
- `artifacts/codex_phase10_smoke/`
- `artifacts/codex_phase10_tuning/`
- `artifacts/codex_phase10_verify/`
- `artifacts/phase11_adaptive24_all/`
- `artifacts/phase11_smoke_cat3/`
- `artifacts/phase11_smoke_cat3_targeted/`
- `artifacts/phase11_smoke_cat3_targeted_pfguard/`
- `artifacts/strategy_optimization/`
- `artifacts/strategy_optimization_v2/`
- `artifacts/tiered_experiments/`

Existing `artifacts/_archived_smoke/` was left in place because it was already an archive.

## Kept For Rewrite

Core data and shared backtest primitives:

- `backend/historical_data.db`
- `backend/data/sectors/ai_tech_tw.json`
- `backend/app/services/screener_service.py`
- `backend/app/services/screener_rules.py`
- `backend/app/services/backtest/historical_data_store.py`
- `backend/app/services/backtest/signal_replay.py`
- `backend/app/services/backtest/trade_simulator.py`
- `backend/app/services/backtest/metrics.py`
- `backend/app/services/backtest/report_generator.py`

Current optimizer implementations kept as reference:

- `backend/app/services/backtest/v1/`
- `backend/app/services/backtest/v2/`
- `backend/scripts/auto_optimize.py`
- `backend/scripts/auto_optimize_v2.py`
- `backend/scripts/optimization.py`
- `backend/scripts/run_backtest.py`

Tests kept for regression while rewriting:

- `backend/tests/test_backtest.py`
- `backend/tests/test_optimizer.py`
- `backend/tests/test_auto_optimize.py`
- `backend/tests/test_entry_tier.py`
- `backend/tests/test_phase11_e2e.py`
- `backend/tests/test_v2_*.py`
- `backend/tests/test_screener.py`
- `backend/tests/test_feature_cache.py`

Clean output folders recreated:

- `artifacts/strategy_optimization/`
- `artifacts/strategy_optimization_v2/`

## Generated Files Removed

All discovered Python `__pycache__` folders and `.pytest_cache/` were removed.

## Small Fix

Fixed `backend/scripts/run_backtest.py --help` by replacing `7%` in argparse help text with `7 percent`.

## Rewrite Notes

Suggested next step is to create a new optimizer package beside v1/v2, for example:

```text
backend/app/services/backtest/v3/
```

Do not delete v1/v2 until the new rewrite has:

- real all-universe dry-run
- worker parallelism
- deterministic min-entry-tier semantics
- zero-trade handling
- no legacy `entry_tier=0` leakage in v3
- tests covering CLI behavior

