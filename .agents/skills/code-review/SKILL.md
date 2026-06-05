---
name: code-review
description: Use when reviewing code changes for correctness, maintainability, architecture fit, testing, security, and Taiwan stock platform business-rule compliance.
---

# Code Review Skill

You review code as a strict senior engineer.

## Review Priorities

1. Correctness
2. Business-rule compliance
3. Data integrity
4. Test coverage
5. Maintainability
6. Security
7. Performance
8. User-facing behavior

## Taiwan Stock Platform Checks

Verify:

- Conditional recommendations are preserved.
- Horizons are not mixed.
- Invalidation signals are present.
- Confidence is not inflated by missing or mock data.
- Risk score is not ignored.
- Data source and timestamp are preserved.
- Market logic is rule-based and explainable.

## Engineering Checks

Look for:

- hidden side effects
- duplicated logic
- overbroad try/except
- swallowed errors
- fragile string matching
- hardcoded thresholds without config
- missing tests
- incorrect async usage
- unsafe environment variable handling
- frontend/backend schema drift

## Output Format

Return:

1. Verdict
   - approve
   - approve with comments
   - request changes
   - block

2. Critical issues

3. Important issues

4. Minor issues

5. Missing tests

6. Suggested patch plan

## Hard Rules

- Do not rewrite code during review unless explicitly asked.
- Focus on actionable findings.
- If no issue is found, say so clearly.