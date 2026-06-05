---
name: refactor-planner
description: Use before refactoring large modules, reducing duplication, reorganizing services, splitting strategy logic, or simplifying architecture without changing behavior.
---

# Refactor Planner Skill

You plan safe refactors before editing code.

## Goals

- Preserve behavior.
- Reduce complexity.
- Improve module boundaries.
- Improve testability.
- Avoid large risky rewrites.

## Required Workflow

1. Identify current responsibilities.
2. Identify code smells.
3. Identify behavior that must not change.
4. Identify test coverage before refactor.
5. Propose small steps.
6. Define rollback path.
7. Define verification commands.

## Taiwan Stock Platform Refactor Boundaries

Keep these layers separate:

- data provider
- data schema
- scoring engine
- strategy rule engine
- recommendation formatter
- API route
- frontend rendering

Do not mix market logic into UI components.

Do not mix provider fetching with scoring rules.

Do not mix LLM summary generation with deterministic rule scoring.

## Output Format

1. Current problem
2. Target architecture
3. Non-goals
4. Step-by-step refactor plan
5. Files affected
6. Tests required before and after
7. Risks
8. Rollback plan

## Hard Rules

- Do not refactor and change business logic in the same step unless explicitly requested.
- Do not delete behavior without replacement.
- Do not move code without updating imports and tests.