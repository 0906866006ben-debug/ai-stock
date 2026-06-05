# AGENTS.md

## Project Identity

This repository is a Taiwan stock AI decision-support platform.

The system is NOT a direct buy/sell signal machine. It must produce conditional, evidence-based, horizon-separated analysis for Taiwan stocks.

Core modules:
- Fundamental analysis
- Technical analysis
- Chip/institutional flow analysis
- News and market narrative analysis
- Watchlist and Telegram notification
- Backtesting and validation infrastructure

## Non-Negotiable Product Principles

1. Never output absolute buy/sell/hold commands.
2. All recommendations must be conditional.
3. Always separate logic by horizon:
   - short-term
   - swing/mid-term
   - long-term
4. Every conditional recommendation must include:
   - direction/status
   - evidence-based reason
   - suitable strategy
   - key observation conditions
   - invalidation signal
   - risk level
   - confidence level
5. No bullish conclusion is allowed without invalidation signals.
6. Insufficient or fallback data must reduce confidence.
7. Mock, estimated, fallback, or stale data must never produce high-confidence recommendations.
8. Do not mix short-term technical strength with long-term fundamental valuation logic.
9. High-risk states must not produce aggressive strategies.
10. Every analysis reason should be traceable to data fields and timestamps.

## Strategy Language

Preferred language:
- wait for confirmed breakout
- wait for pullback to support
- bullish but avoid chasing
- observe only
- reduce chasing risk
- valuation is high despite solid fundamentals
- strength is not confirmed without chip support
- short-term strength conflicts with long-term valuation risk

Forbidden language:
- buy now
- must buy
- must sell
- guaranteed
- sure win
- no risk
- target price without conditions
- high confidence based only on mock/fallback data

## Architecture Rules

Before making major code changes:
1. Inspect the current architecture.
2. Identify affected files.
3. Write an implementation plan.
4. State non-goals.
5. Define test cases.
6. Only then edit code.

Do not rewrite large modules unless explicitly required.

Prefer small, reviewable patches.

## Data Rules

All market logic must be:
- rule-based
- explainable
- backtestable
- data-source-aware
- timestamp-aware

Important data families:
- price and volume
- moving averages
- RSI, MACD, KD, Bollinger Bands if still used
- institutional net buy/sell
- institutional buying intensity
- margin trading
- securities lending
- day-trading ratio
- market regime
- sector/peer group strength
- revenue, EPS, ROE, margin, valuation
- news category and sentiment

Never invent unavailable fields. If a field is unavailable, mark it as missing and lower confidence.

## Backtesting Rules

Any new strategy rule must specify:
- entry condition
- exit condition
- invalidation condition
- holding horizon
- universe
- benchmark
- transaction cost assumption
- slippage assumption
- lookahead-bias prevention
- survivorship-bias risk
- evaluation metrics

Required metrics:
- CAGR
- max drawdown
- win rate
- profit factor
- Sharpe or Sortino if available
- average holding days
- turnover
- number of trades
- performance by market regime

## Testing Commands

Before finalizing backend changes, try relevant checks such as:

```bash
pytest