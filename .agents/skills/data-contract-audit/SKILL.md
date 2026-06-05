---
name: data-contract-audit
description: Use to audit data schemas, API payloads, Pydantic models, provider outputs, timestamps, missing-data handling, and traceability for the Taiwan stock AI platform.
---

# Data Contract Audit Skill

You audit data contracts across providers, backend services, schemas, and frontend consumers.

## Scope

Use this skill for:

- Pydantic models
- FastAPI response schemas
- provider output formats
- frontend TypeScript interfaces
- database schemas
- CSV/parquet schemas
- mock/fallback data handling
- timestamp and source attribution

## Required Checks

1. Field names are consistent.
2. Types are explicit.
3. Units are documented.
4. Date/time fields include timezone or market-date meaning.
5. Data source is traceable.
6. Staleness is detectable.
7. Missing-data behavior is explicit.
8. Mock/fallback data is flagged.
9. Confidence logic reacts to data quality.
10. Frontend does not assume unavailable fields.

## Required Output

1. Data flow map
2. Schema mismatch list
3. Missing fields
4. Ambiguous fields
5. Timestamp risks
6. Mock/fallback leakage risks
7. Recommended schema changes
8. Test cases

## Hard Rules

- Do not silently rename fields.
- Do not hide missing data.
- Do not allow mock data to look like real data.
- Do not allow frontend to display high-confidence analysis without source and timestamp.