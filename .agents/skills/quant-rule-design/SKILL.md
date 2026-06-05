---
name: quant-rule-design
description: Use when converting discretionary Taiwan stock analysis ideas into rule-based, testable, backtestable quant logic with explicit fields, thresholds, scoring, risk, confidence, and invalidation.
---

# Quant Rule Design Skill

You convert market ideas into formal quantitative rules.

## Required Output

For every rule, produce:

1. Rule name
2. Purpose
3. Applicable horizon
4. Required input fields
5. Calculation formula
6. Thresholds
7. Signal meaning
8. Risk implication
9. Confidence impact
10. Invalidation condition
11. Missing-data behavior
12. Backtest method

## Platform Scoring Model

Keep three scores separate:

- Signal Score: strength of opportunity
- Risk Score: downside and uncertainty
- Confidence Score: reliability of evidence

Never merge these into one opaque score.

## Rule Design Principles

- Technical and chip data often dominate short-term risk.
- Fundamentals dominate long-term quality and valuation.
- News can modify risk and confidence, but should not override hard price/flow deterioration unless explicitly designed.
- Market regime can suppress confidence or reduce aggressiveness.
- Liquidity filters must be applied before strategy aggressiveness.

## Required Guardrails

1. Insufficient data lowers confidence.
2. Stale data lowers confidence.
3. Mock data cannot generate high confidence.
4. High risk caps strategy aggressiveness.
5. Horizon conflict must be explicitly reported.
6. Strong technicals without chip support should not become aggressive bullish output.
7. Good fundamentals with short-term technical breakdown must be treated as horizon conflict.

## Example Output Structure

```yaml
rule_id:
  name:
  horizon:
  inputs:
  formula:
  pass_condition:
  weak_condition:
  fail_condition:
  signal_score_effect:
  risk_score_effect:
  confidence_score_effect:
  invalidation:
  missing_data_behavior:
  backtest_notes: