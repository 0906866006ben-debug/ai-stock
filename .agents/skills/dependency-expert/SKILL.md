---
name: dependency-expert
description: Use when adding, removing, upgrading, or debugging dependencies, package managers, Python virtual environments, Node packages, build tools, or version conflicts.
---

# Dependency Expert Skill

You manage dependencies conservatively.

## Workflow

1. Identify package manager.
2. Inspect dependency files.
3. Check current runtime versions.
4. Determine why the dependency is needed.
5. Prefer existing dependencies when sufficient.
6. Avoid unnecessary major upgrades.
7. Update lockfiles when appropriate.
8. Run install/build/test commands if available.

## Python Checks

Inspect:

- pyproject.toml
- requirements.txt
- poetry.lock
- uv.lock
- Pipfile
- virtual environment assumptions

## Node Checks

Inspect:

- package.json
- package-lock.json
- pnpm-lock.yaml
- yarn.lock
- vite/next config

## Hard Rules

- Do not add heavy dependencies for simple tasks.
- Do not upgrade unrelated packages.
- Do not remove lockfiles.
- Do not expose secrets from .env.
- State clearly if installation or tests could not be run.