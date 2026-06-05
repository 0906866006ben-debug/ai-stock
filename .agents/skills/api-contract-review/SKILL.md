---
name: api-contract-review
description: Use when reviewing or changing FastAPI routes, API payloads, response schemas, error handling, OpenAPI behavior, frontend-backend contracts, or Telegram/watchlist APIs.
---

# API Contract Review Skill

You review API behavior and compatibility.

## Required Checks

1. Endpoint path and method
2. Query/body parameters
3. Response schema
4. Error schema
5. Status codes
6. Validation behavior
7. Backward compatibility
8. Frontend consumer compatibility
9. Authentication or token concerns if applicable
10. Source/timestamp traceability

## Taiwan Stock API Requirements

Analysis APIs should preserve:

- stock id
- market date
- data timestamp
- data source
- horizon-separated analysis
- risk level
- confidence level
- invalidation signals
- missing-data warnings
- mock/fallback flags

## Output Format

1. Contract summary
2. Breaking changes
3. Schema issues
4. Error-handling issues
5. Frontend impact
6. Test cases
7. Recommended patch

## Hard Rules

- Do not silently change response fields.
- Do not return fake success when provider data fails.
- Do not hide missing fields.
- Do not expose internal stack traces to users.