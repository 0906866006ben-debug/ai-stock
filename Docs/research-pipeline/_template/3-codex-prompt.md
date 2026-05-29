# Stage 3 - Codex Implementation Contract

> Owner: Claude writes this contract; Codex executes it. The runner prepends
> project guardrails automatically, so do not duplicate them here.
>
> This prompt must be self-contained and bounded. Codex may inspect the repo to
> implement and verify the task, but must not expand the research decision.

## Contract Metadata

| Field | Value |
|---|---|
| Task ID | `<task-id>` |
| Task title | `<short title>` |
| Task type | `Measurement Only / Additive Feature / Bug Fix / Strategy Change` |
| Research source | `tasks/<task-id>/1-research.md` |
| Claude decision source | `tasks/<task-id>/2-plan.md` |
| Human approval | `<Yes - YYYY-MM-DD / Pending>` |

## Read First

Read these files before making changes:

1. `<required guardrail/design path, if not automatically prepended>`
2. `Docs/research-pipeline/tasks/<task-id>/1-research.md`
3. `Docs/research-pipeline/tasks/<task-id>/2-plan.md`
4. `<relevant existing module/test/artifact>`

## Objective

Implement exactly this one outcome:

`<single, testable objective>`

## Decision Boundary

This task is **`<Task Type>`**.

- Evidence-supported work allowed now: `<allowed action>`.
- Unresolved research questions that must remain unresolved: `<items>`.
- Stop after: `<explicit endpoint, test state, or report artifact>`.

## Required Changes

| # | Path / module ownership | Required behavior | Acceptance evidence |
|---|---|---|---|
| `1` | `<path>` | `<precise change>` | `<test/output>` |

## Must Not Change

- Do not modify `<validated signal/rule/score/grade/threshold/gate logic, if applicable>`.
- Do not introduce `<optimizer dimensions, live wiring, UI fields, external calls, etc.>`.
- Do not fabricate missing data, evidence, metrics, or API results.
- Do not implement any follow-on phase.
- `<task-specific prohibition>`.

## Data And Integrity Requirements

Complete or remove items that do not apply; do not leave ambiguity.

- Point-in-time / no-look-ahead rule: `<requirement or N/A with reason>`.
- Data missing/failure behavior: `<honest fallback or error behavior>`.
- Sample-size / signal-frequency guard: `<minimum evidence/reporting or N/A>`.
- Anti-overfit boundary: `<fixed params / measurement only / revalidation requirement / N/A>`.
- User-facing language constraint: `<required assertions or N/A>`.

## Implementation Details

Specify contracts rather than open-ended design freedom.

### Interfaces / Schema

```text
<function signatures, CLI arguments, response fields, artifact columns, or N/A>
```

### Behavior Cases

| Case | Expected behavior |
|---|---|
| `<normal input>` | `<output>` |
| `<missing/empty/error input>` | `<output without fabrication>` |
| `<boundary case>` | `<output>` |

## Required Tests

Add or update these tests. No network calls in unit tests unless explicitly stated.

| Test file | Required coverage |
|---|---|
| `<backend/tests/...>` | `<behavior and failure modes>` |

## Verification Commands

Run these in order and do not report completion unless the relevant commands pass:

```powershell
.venv\Scripts\python.exe -m pytest <targeted-tests> -q
.venv\Scripts\python.exe -m pytest backend\tests\ -q
```

For frontend work, also run:

```powershell
npm.cmd run lint
npm.cmd run build
```

Remove commands that genuinely do not apply and explain why in the final report.

## Required Final Report

When finished, report only verified results:

1. Files changed and the behavior added or fixed.
2. Tests/commands executed with pass/fail results.
3. Required metrics, schema, artifact path, or sample API URL:
   - `<required output>`
4. Remaining known limitations or data gaps.
5. Exact next command for the human, only if the task requires a manual real-data run.

## Stop Condition

Stop when the required changes and verification above are complete. Do not
start related refactors, new research hypotheses, parameter tuning, or the
next phase.
