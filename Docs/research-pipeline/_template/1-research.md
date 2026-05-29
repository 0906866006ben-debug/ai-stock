# Stage 1 - Gemini Deep Research Report

> Owner: Gemini Deep Research. Purpose: collect evidence and testable hypotheses.
> Do not write implementation instructions for Codex. Claude decides whether
> the research is actionable after checking it against the repository.

## Instructions For Gemini

Use this exact section order. Keep factual claims traceable to sources. Clearly
separate external evidence, repository facts supplied in the prompt, and your
own inferences. If evidence is missing or contradictory, say so.

For strategy, screening, optimization, or backtest topics:

- Treat thresholds and observed performance as hypotheses, not truths.
- Identify look-ahead, survivorship, PIT, sample-size, repeated-OOS, and
  overfitting risks.
- Recommend `Measurement Only` unless evidence is strong enough to justify a
  narrowly scoped change.

## Research Metadata

| Field | Value |
|---|---|
| Task ID | `<task-id>` |
| Research question | `<one decision-oriented question>` |
| Requested by | `<human / Claude / other>` |
| Research date | `<YYYY-MM-DD>` |
| Recommended task type | `Measurement Only / Additive Feature / Bug Fix / Strategy Change / Need More Data` |

## 1. Research Question

State one precise question that this report answers.

## 2. Context Provided

List only context supplied by the user or existing project documents. Do not
claim these items were independently verified in the repository.

| Provided fact or constraint | Source supplied | Why it matters |
|---|---|---|
| `<fact>` | `<file/message/report>` | `<relevance>` |

## 3. Executive Findings

Provide 3-7 concise findings. Each finding must be classified.

| ID | Finding | Type | Confidence | Action relevance |
|---|---|---|---|---|
| `F-01` | `<finding>` | `External Evidence / Provided Repo Context / Inference / Unknown` | `High / Medium / Low` | `<why it matters>` |

## 4. External Evidence Register

Include a URL and publication/access date for every external factual claim.
Use primary sources when possible.

| ID | Claim supported | Source title | URL | Published/accessed date | Evidence quality | Limitations |
|---|---|---|---|---|---|---|
| `E-01` | `<claim>` | `<title>` | `<url>` | `<YYYY-MM-DD>` | `Primary / Secondary / Anecdotal` | `<limits>` |

## 5. Repository-Relevant Implications

Describe how the evidence may relate to this project. Mark all repository
statements not directly verified by Gemini as `Claude must verify`.

| Area or module | Possible implication | Status | Verification needed in repo |
|---|---|---|---|
| `<area>` | `<implication>` | `Claude must verify / Supported by provided context` | `<files/tests/data to inspect>` |

## 6. Hypotheses And Falsification Tests

Each proposal must be falsifiable before it becomes implementation work.

| Hypothesis ID | Hypothesis | Supporting evidence IDs | Falsification test | Required data | Pass/fail signal |
|---|---|---|---|---|---|
| `H-01` | `<hypothesis>` | `E-01, F-01` | `<test>` | `<data>` | `<criterion>` |

## 7. Alternatives Considered

| Option | Benefits | Costs / risks | Evidence support | Recommendation |
|---|---|---|---|---|
| `<option>` | `<benefit>` | `<risk>` | `<strong/weak/none>` | `Prefer / Defer / Reject` |

## 8. Data Integrity And Overfitting Review

Complete this section even if the topic is not a trading strategy; write `N/A`
with a reason where it truly does not apply.

| Risk | Present? | Evidence / reason | Required safeguard |
|---|---|---|---|
| Look-ahead leakage | `Yes / No / Unknown / N/A` | `<reason>` | `<safeguard>` |
| Point-in-time availability | `Yes / No / Unknown / N/A` | `<reason>` | `<safeguard>` |
| Survivorship bias | `Yes / No / Unknown / N/A` | `<reason>` | `<safeguard>` |
| Small sample / degenerate metric | `Yes / No / Unknown / N/A` | `<reason>` | `<safeguard>` |
| Repeated tuning on seen OOS data | `Yes / No / Unknown / N/A` | `<reason>` | `<safeguard>` |
| Data/API availability risk | `Yes / No / Unknown / N/A` | `<reason>` | `<safeguard>` |

## 9. Recommended Next Step

Choose exactly one:

- `Measurement Only`
- `Additive Feature`
- `Bug Fix`
- `Strategy Change`
- `Need More Data`
- `Reject`

**Recommendation:** `<choice>`

**Rationale:** `<why this is the least risky evidence-supported next step>`

**Do not do yet:** `<changes that are premature or unsupported>`

## 10. Questions For Claude

List the decisions Claude must make after inspecting the current codebase.

1. `<question>`
2. `<question>`

## Appendix: Raw Notes Or Source Extracts

Optional. Keep quotations short and preserve source URLs.
