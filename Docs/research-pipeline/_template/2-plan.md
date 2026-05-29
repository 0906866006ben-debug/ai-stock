# Stage 2 - Claude Synthesis Decision And Plan

> Owner: Claude Code. Inputs: `1-research.md`, the current repository, relevant
> tests/artifacts, and project guardrails. Purpose: decide whether the research
> justifies work, constrain the scope, and author `3-codex-prompt.md`.
>
> Do not treat Gemini findings as implemented facts until verified in the repo.

## Synthesis Metadata

| Field | Value |
|---|---|
| Task ID | `<task-id>` |
| Claude model / effort | `<model and effort, if known>` |
| Research file reviewed | `1-research.md` |
| Repository checked at | `<YYYY-MM-DD HH:mm>` |
| Decision | `Proceed / Measurement Only / Reject / Need More Data` |
| Task type for Codex | `Measurement Only / Additive Feature / Bug Fix / Strategy Change / None` |

## 1. Decision

**Decision:** `<Proceed / Measurement Only / Reject / Need More Data>`

**One-paragraph rationale:**  
`<Explain why the evidence and repository state support this decision.>`

## 2. Research Claims Verified Against The Repository

Separate confirmed facts from mismatches and unverified assumptions.

| Research claim / hypothesis ID | Repo verification result | Evidence inspected | Consequence |
|---|---|---|---|
| `<F-01 / H-01>` | `Confirmed / Partly confirmed / Not present / Contradicted / Not verifiable` | `<path, test, artifact>` | `<impact on decision>` |

## 3. Current System Facts Codex May Rely On

Only list facts verified by Claude in code/tests/artifacts.

| Fact | Evidence path or command | Stability / caution |
|---|---|---|
| `<verified fact>` | `<file/test/artifact>` | `<caution>` |

## 4. Inferences And Unknowns

| Item | Classification | Why it is not established fact | Handling |
|---|---|---|---|
| `<item>` | `Inference / Unknown / External-only evidence` | `<reason>` | `Measure / Defer / Explicit assumption` |

## 5. Scope Decision

### Allowed This Task

- `<one narrowly scoped allowed result>`

### Explicitly Out Of Scope

- `<rule/feature/refactor/production wiring that must not be touched>`

### Files Or Modules Expected To Change

| Path / module | Allowed purpose of change |
|---|---|
| `<path>` | `<reason>` |

## 6. Integrity And Guardrail Check

Complete before authoring a Codex prompt.

| Check | Verdict | Required instruction for Codex |
|---|---|---|
| Strategy signal/score/threshold/gate logic changes? | `No / Yes - revalidation required / N/A` | `<instruction>` |
| Measurement-only boundary preserved? | `Yes / No / N/A` | `<instruction>` |
| No look-ahead / PIT requirement | `Satisfied / Must implement / N/A` | `<instruction>` |
| Survivorship or coverage limitation | `Known / Must report / N/A` | `<instruction>` |
| Overfitting exposure | `Acceptable / Red flag / N/A` | `<instruction>` |
| User-facing investment-action wording risk | `Absent / Must assert / N/A` | `<instruction>` |

## 7. Implementation Plan

Write only if the decision allows Codex work.

| Step | Change | Files / modules | Why needed | Verification |
|---|---|---|---|---|
| `1` | `<change>` | `<path>` | `<reason>` | `<test/check>` |

## 8. Acceptance Criteria

Codex must meet every checked criterion before stopping.

- [ ] The requested behavior is implemented only within the allowed scope.
- [ ] No deferred or forbidden behavior was introduced.
- [ ] Required unit/no-network tests are added or updated.
- [ ] Targeted tests pass.
- [ ] Full applicable test suite passes, or failures are reported exactly.
- [ ] Required measurement/report artifacts are produced, if this is measurement-only work.
- [ ] No unsupported claims are presented as validated results.

### Required Commands

```powershell
<targeted test command>
<full suite command>
```

### Required Result Fields Or Metrics

| Output | Required content |
|---|---|
| `<report/artifact/response>` | `<schema/metrics/diagnostics>` |

## 9. Codex Prompt Authoring Checklist

Before filling `3-codex-prompt.md`, confirm:

- [ ] It names the exact task type and stop boundary.
- [ ] It lists the required read-first documents.
- [ ] It states allowed changes and must-not-change constraints.
- [ ] It includes concrete tests and report outputs.
- [ ] It does not ask Codex to decide an unresolved research question by editing production code.

## 10. Human Checkpoint

| Item | Value |
|---|---|
| Human approved scope? | `Pending / Yes / No` |
| Human notes | `<notes>` |
| Approved to run Codex? | `Pending / Yes / No` |
