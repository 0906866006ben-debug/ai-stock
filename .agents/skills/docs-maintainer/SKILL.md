---
name: docs-maintainer
description: Use when creating or updating project documentation, architecture docs, implementation plans, strategy specs, Codex prompts, Claude prompts, README, or development handoff documents.
---

# Docs Maintainer Skill

You maintain clear technical documentation for humans and coding agents.

## Documentation Types

Use this skill for:

- README
- AGENTS.md
- strategy specification
- implementation plan
- API documentation
- backtest documentation
- data schema documentation
- Claude/Codex handoff prompts
- development task breakdowns

## Required Style

- Be precise.
- Use headings.
- Separate current behavior from planned behavior.
- Separate goals from non-goals.
- Include acceptance criteria.
- Include test requirements.
- Include known risks.
- Avoid vague instructions.

## Taiwan Stock Platform Documentation Rules

Always preserve:

- conditional recommendation principle
- horizon separation
- risk/confidence separation
- invalidation requirement
- data traceability
- no absolute buy/sell command
- mock/fallback data confidence cap
- backtestability requirement

## Output Format

When updating docs, include:

1. What changed
2. Why it changed
3. Files updated
4. Remaining TODOs
5. Any assumptions

## Hard Rules

- Do not remove important project constraints.
- Do not simplify away risk controls.
- Do not turn strategy logic into vague marketing text.