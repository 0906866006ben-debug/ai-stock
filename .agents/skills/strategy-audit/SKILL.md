---
name: strategy-audit
description: Use to audit Taiwan stock trading or investing strategy logic for quantifiability, data availability, lookahead bias, backtestability, risk controls, horizon separation, and conditional recommendation quality.
---

# Strategy Audit Skill

You are auditing strategy logic for a Taiwan stock AI decision-support platform.

The system must not give absolute buy/sell/hold commands. It must produce conditional, horizon-separated, evidence-based analysis.

## Audit Objectives

Evaluate whether the strategy is:

1. Quantifiable
2. Data-available in Taiwan market context
3. Backtestable
4. Free from lookahead bias
5. Free from survivorship bias as much as possible
6. Horizon-separated
7. Risk-controlled
8. Explainable
9. Suitable for conditional recommendations
10. Compatible with the platform's decision-support positioning

## Required Checks

### 1. Data Availability

For each rule, check:

- Required data field
- Source candidate
- Frequency
- Delay
- Timestamp
- Missing-data risk
- Whether it can be obtained historically
- Whether it is real-time, delayed, daily, monthly, or quarterly

### 2. Quantifiability

Reject vague rules unless converted to measurable logic.

Examples:

Bad:
- strong momentum
- good fundamentals
- institutional support is good
- news is positive

Good:
- close > MA20 and MA20 slope > 0
- monthly revenue YoY > 10%
- foreign investors net buy for 3 of last 5 sessions
- sentiment score > 0.3 from classified news sources

### 3. Lookahead Bias

Check for:

- Using financial statements before release date
- Using full-month revenue before announcement date
- Using closing price before signal timestamp
- Using future index constituents
- Using revised data without point-in-time awareness

### 4. Horizon Separation

Separate:

- Short-term: price, volume, technicals, institutional flow, event risk
- Swing/mid-term: trend, sector flow, earnings/revenue momentum, market regime
- Long-term: business quality, valuation, ROE, margins, revenue cycle, balance-sheet risk

Flag any mixed logic.

### 5. Conditional Recommendation Quality

Every recommendation must include:

- direction/status
- reason
- condition
- invalidation point
- risk level
- confidence level

No bullish output without invalidation.

### 6. Risk Controls

Check:

- downside invalidation
- liquidity risk
- gap risk
- high day-trading ratio
- broker concentration
- sector contagion
- market regime
- valuation risk
- earnings announcement risk
- ex-dividend or capital action risk

### 7. Backtesting Design

For each rule or strategy, specify:

- entry signal
- exit signal
- invalidation signal
- stop condition
- holding period
- rebalancing frequency
- universe
- benchmark
- transaction cost
- slippage
- metrics
- regime segmentation

## Output Format

Return:

1. Executive verdict
   - viable
   - viable with modifications
   - not currently quantifiable
   - not suitable for this platform

2. Critical issues

3. Rule-by-rule audit table:
   - rule
   - data needed
   - data availability
   - quantifiability
   - bias risk
   - fix

4. Required redesign

5. Backtest specification

6. Conditional recommendation template

7. Implementation notes for Codex

## Hard Rules

- Do not implement code unless explicitly requested.
- Do not approve vague discretionary rules.
- Do not allow high confidence from insufficient data.
- Do not allow aggressive strategy under high-risk states.
- Treat all thresholds as v1 hypotheses unless backed by backtest results.