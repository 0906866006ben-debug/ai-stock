---
name: backtest-validation
description: Use when designing, reviewing, implementing, or debugging backtests for Taiwan stock strategies, including bias prevention, metrics, transaction costs, slippage, and regime-based validation.
---

# Backtest Validation Skill

You ensure backtests are realistic, reproducible, and bias-aware.

## Required Checks

### Bias Prevention

Check for:

- Lookahead bias
- Survivorship bias
- Rebalanced universe leakage
- Financial statement release-date leakage
- Monthly revenue announcement-date leakage
- Same-day close execution assumptions
- Future benchmark or sector membership leakage

### Trading Assumptions

Require:

- Entry timestamp
- Exit timestamp
- Execution price assumption
- Transaction cost
- Slippage
- Tax or fee assumption if applicable
- Liquidity filter
- Position sizing
- Max position count
- Rebalance frequency

### Metrics

Required:

- CAGR
- Max drawdown
- Win rate
- Profit factor
- Number of trades
- Average holding period
- Turnover
- Exposure
- Benchmark comparison
- Performance by market regime

Optional:

- Sharpe
- Sortino
- Calmar
- Tail risk
- Monthly return heatmap
- Rolling drawdown
- Sector contribution

## Taiwan Market Considerations

Consider:

- Daily price limit
- Liquidity constraints
- Ex-dividend behavior
- Earnings and revenue announcement delays
- Institutional flow timestamp
- Holiday calendar
- Sector rotation
- TAIEX regime
- OTC vs listed market differences

## Output Format

1. Backtest verdict
2. Bias risks
3. Assumption table
4. Metrics coverage
5. Missing validation
6. Required fixes
7. Suggested test cases
8. Whether result is trustworthy enough for strategy use

## Hard Rules

- Never accept a backtest that uses future data.
- Never accept performance without transaction costs.
- Never accept high confidence from short sample size.
- Never treat one stock or one period as proof.