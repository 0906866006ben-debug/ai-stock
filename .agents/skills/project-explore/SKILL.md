---
name: project-explore
description: Use when asked to understand, inspect, map, or explain the repository before coding. Do not modify files unless explicitly requested.
---

# Project Explore Skill

You are responsible for exploring the repository safely before any implementation.

## Goals

- Understand the current architecture.
- Identify backend, frontend, data, strategy, and test layers.
- Locate key entry points.
- Produce a concise project map.
- Avoid unnecessary file edits.

## Workflow

1. Inspect repository structure.
2. Identify framework and package managers.
3. Locate backend entry points.
4. Locate frontend entry points.
5. Locate analysis logic.
6. Locate data providers.
7. Locate tests.
8. Locate configuration files.
9. Summarize dependencies and runtime assumptions.
10. Report risks, missing documentation, and unclear boundaries.

## Required Output

Return:

1. Repository map
2. Main runtime flow
3. Important files
4. Data flow
5. Test locations
6. Build/run commands discovered
7. Risks or unclear areas
8. Recommended next actions

## Rules

- Do not edit files.
- Do not invent architecture.
- If something is not found, say it is not found.
- Prefer evidence from actual files over assumptions.