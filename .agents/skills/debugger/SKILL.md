---
name: debugger
description: Use when investigating errors, failing tests, broken API responses, frontend crashes, wrong stock analysis output, or inconsistent data behavior.
---

# Debugger Skill

You diagnose before modifying.

## Workflow

1. Reproduce the issue if possible.
2. Identify expected behavior.
3. Identify actual behavior.
4. Locate the smallest failing path.
5. Inspect logs, stack traces, tests, and related code.
6. Form hypotheses.
7. Test hypotheses.
8. Propose minimal fix.
9. Apply fix only if requested.
10. Run relevant tests.

## Required Output

1. Problem summary
2. Reproduction steps
3. Root cause
4. Files involved
5. Minimal fix
6. Tests run
7. Regression risk

## Taiwan Stock Platform Debug Checks

When output analysis is wrong, inspect:

- provider data
- schema conversion
- missing-data flags
- confidence calculation
- risk calculation
- horizon routing
- recommendation template
- frontend rendering

## Hard Rules

- Do not make large refactors while debugging.
- Do not mask errors with broad fallback behavior.
- Do not convert real data failure into fake success.
- Do not remove tests to make failures pass.