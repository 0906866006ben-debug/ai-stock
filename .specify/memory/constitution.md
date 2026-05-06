<!--
SYNC IMPACT REPORT
==================
Version change: 1.0.0 → 1.1.0  (MINOR — 5 new principles added, existing principles
refined and split to align with user-supplied 10-principle definition)

Modified principles:
  - I. Structured Backend API       → I. FastAPI Backend Stack (refined wording)
  - II. Modern Frontend Architecture → II. Next.js Frontend Stack (refined wording)
  - III. Resilient Data Access       → V. Finance Data Integration
                                     + VI. Resilient Fallback on Data Failure (split)
  - IV. Structured & Honest AI Output → IV. Structured AI Output (NON-NEGOTIABLE)
                                      + IX. Financial Analysis Disclaimer (split)
  - V. Simplicity & Minimalism      → X. Minimal Rewrite Policy (repositioned)

Added principles:
  - III. Stable API Contracts (new)
  - VII. MVP Scope (new)
  - VIII. API Key Security & Secret Management (new)

Removed sections:
  - None

Templates reviewed:
  - .specify/templates/plan-template.md   ✅ Constitution Check section is generic — no update needed
  - .specify/templates/spec-template.md   ✅ Aligns with updated principles — no update needed
  - .specify/templates/tasks-template.md  ✅ Phase structure covers backend + frontend — no update needed

Deferred TODOs:
  - None — all 10 user-supplied principles fully encoded.
-->

# AI Stock Assistant Constitution

## Core Principles

### I. FastAPI Backend Stack

The backend MUST be implemented with FastAPI. Pydantic MUST be used for all
data modeling. PydanticAI MUST be used wherever structured AI output is
required. LangGraph MUST be used for multi-step stock analysis workflows.
No other backend framework may be substituted without an explicit constitutional
amendment.

### II. Next.js Frontend Stack

The frontend MUST use the Next.js App Router with TypeScript. All styling MUST
use Tailwind CSS. Stock price charts MUST use lightweight-charts. Analysis
visualizations MUST use Plotly or Recharts. No client-side API keys or secrets
are permitted.

### III. Stable API Contracts

All API responses MUST use stable Pydantic schemas. Schema changes MUST be
backward-compatible or explicitly versioned. Frontend consumers MUST be able
to rely on schema stability across iterations; breaking schema changes are a
critical defect unless versioned.

### IV. Structured AI Output (NON-NEGOTIABLE)

AI output MUST be structured JSON at all times. Free-form plain-text responses
are not acceptable. The JSON payload MUST include at minimum: `summary`,
`trend`, `confidence`, `risks`, `catalysts`, and `recommendation`. Any
deviation from structured output is a critical defect.

### V. Finance Data Integration

External finance APIs (Polygon, Finnhub, Financial Modeling Prep, yfinance)
MUST be used as available based on configured API keys. Integration MUST be
additive — the absence of any single provider MUST NOT prevent the system from
functioning with the remaining providers.

### VI. Resilient Fallback on Data Failure

When API keys are missing or external finance APIs fail, the system MUST return
mock fallback data instead of crashing or propagating errors to the end user.
Crashing on a missing or unreachable data source is a critical defect.

### VII. MVP Scope

The MVP MUST deliver exactly these five capabilities: stock lookup, chart
display, news display, financial summary, and AI analysis. Features outside
this defined MVP scope MUST NOT be implemented without explicit user approval.
Scope creep is a violation of this principle.

### VIII. API Key Security & Secret Management

The system MUST NEVER expose API keys in code, API responses, logs, or
client-side bundles. `.env` MUST NOT be committed to version control. All
secrets MUST be read from `.env` at runtime via environment variables. This
rule has no exceptions.

### IX. Financial Analysis Disclaimer (NON-NEGOTIABLE)

All AI-generated content MUST be clearly positioned as financial analysis
support only — it MUST NOT be presented as financial advice. The AI MUST NEVER
fabricate or invent financial facts. When data is missing or incomplete, the AI
MUST explicitly state this in its output. Misrepresenting AI output as
actionable financial advice is a critical defect.

### X. Minimal Rewrite Policy

The codebase MUST NOT be rewritten wholesale unless the user explicitly
requests it. Complexity MUST be justified before introduction. Prefer the
simplest solution that satisfies current requirements; YAGNI applies. Premature
abstractions and over-engineering are violations of this principle.

## Technology Stack

### Backend

- **Runtime**: Python 3.11+
- **Web framework**: FastAPI
- **Schema validation**: Pydantic v2
- **AI integration**: PydanticAI (structured output), LangGraph (multi-step workflows)
- **Finance data**: Polygon API, Finnhub, Financial Modeling Prep, yfinance

### Frontend

- **Framework**: Next.js (App Router)
- **Language**: TypeScript
- **Styling**: Tailwind CSS
- **Stock charts**: lightweight-charts
- **Analysis visualizations**: Plotly or Recharts

## Git Safety & Development Workflow

- `.env`, `.venv`, and `node_modules` MUST NOT be committed to version control.
- Feature branches MUST follow the `###-feature-name` naming convention.
- All pull requests MUST be reviewed for compliance with the Core Principles
  above before merge.
- Violations of Core Principles MUST be documented and justified in the
  `Complexity Tracking` table of the relevant `plan.md`.

## Governance

This constitution supersedes all other project-level practices and documents.
Amendments MUST include: a version bump following semantic versioning, a written
rationale, and a migration plan for any breaking changes. All code reviews MUST
verify compliance with these principles. Use `CLAUDE.md` for runtime development
guidance; the constitution governs non-negotiable architectural rules.

**Semantic versioning policy**:
- MAJOR — backward-incompatible principle removals or redefinitions
- MINOR — new principle or section added / materially expanded
- PATCH — clarifications, wording, or non-semantic refinements

**Version**: 1.1.0 | **Ratified**: 2026-05-07 | **Last Amended**: 2026-05-07
