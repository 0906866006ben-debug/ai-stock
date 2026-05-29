# Internal Backtest Boundary

`backend.app.services.backtest` is an internal validation module. It may import
trade simulators, optimizers, numeric `entry_tier` handling, and position
multipliers for research and walk-forward validation.

User-facing `/analyze*` responses and CANSLIM `ScreeningResult` output should
surface condition matches, evidence, grades, and interpretation only. They should
not expose simulator internals, position sizing, optimizer recommendations, or
numeric tier multipliers as product guidance.
