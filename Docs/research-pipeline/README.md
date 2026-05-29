# Research → Synthesis → Implementation pipeline

A checkpointed three-agent relay for building features in this repo. It
formalizes the workflow you were already doing by hand (Gemini deep-research
report → Claude plan + Codex prompt → Codex writes the code).

**Checkpointed by design:** a human reviews between every stage. Nothing runs
end-to-end unattended — that is the deliberate antidote to "一次產出問題很多".

```
 Stage 1            Stage 2                    Stage 3
 RESEARCH           SYNTHESIS                  IMPLEMENTATION
 Gemini    ──▶  Claude (Claude Code)  ──▶  Codex CLI
 deep research   reads research + repo,      executes the prompt,
                 writes plan + prompt         writes code + tests
   │                  │      │                     │
1-research.md     2-plan.md  3-codex-prompt.md   codex-last-message.md
   │                  │      │                     │
  [paste]        [you review][you review]       [you review diff]
```

## What is automated vs. manual (be honest about the tooling)

All three CLIs are now installed (npm global) and authenticated, callable headless:

| Stage | Tool | Headless invocation | Notes |
|-------|------|---------------------|-------|
| 1 Research | `gemini` | `gemini --skip-trust -p "<prompt>"` | OAuth personal (free). `--skip-trust` is required in non-interactive runs (trusted-folders gate). NB: the CLI is agentic chat + web tools, **not** the web app's "Deep Research" mode — for the heaviest reports you may still prefer the web UI and paste into `1-research.md`. |
| 2 Synthesis | `claude` | `echo "<prompt>" \| claude -p` | Shares your existing Claude Code login (`~/.claude/.credentials.json`). A headless `claude -p` is a **fresh** agent with no memory of your interactive session — for synthesis you usually still want the interactive Claude Code session that already has context. |
| 3 Implementation | `codex` | `run_pipeline.ps1 codex <task>` | Non-interactive, guardrails auto-prepended. |

Stage 3 is wired into this runner. Stages 1–2 can now also be scripted, but are
left as checkpoints by default (research can be wrong/already-done; synthesis
benefits from the interactive session's context). See the offer at the bottom.

## Per-task layout

Each task is a folder under `tasks/<task-id>/`:

- `1-research.md` — Gemini's structured evidence report: claims, sources,
  hypotheses, falsification tests, and data-integrity risks (Stage 1)
- `2-plan.md` — Claude's repository-verified decision, bounded scope, and
  acceptance criteria (Stage 2)
- `3-codex-prompt.md` — Claude's self-contained implementation contract for
  Codex: exact changes, prohibitions, tests, report, and stop boundary
- `codex-composed-prompt.md` — guardrails + prompt, as actually sent (generated)
- `codex-last-message.md` — Codex's final message (generated)

`tasks/` is the only thing you create; `_template/` holds the stage stubs.
For copy-ready commands and handoff prompts, open
[`_template/COMMANDS.md`](./_template/COMMANDS.md).

## Usage

```powershell
# from Docs/research-pipeline/

# 1. scaffold a task
./run_pipeline.ps1 new distday-hold-rule "TW hold-period calibration"

# 2. give tasks/distday-hold-rule/1-research.md to Gemini as its fixed output
#    format, then place Gemini's completed structured report back in that file.
#    then, in a Claude Code session:
#    "synthesize the research-pipeline task distday-hold-rule"
#    -> Claude fills 2-plan.md and 3-codex-prompt.md. REVIEW them.

# 3. run the Codex implementation leg (guardrails auto-prepended)
./run_pipeline.ps1 codex distday-hold-rule
./run_pipeline.ps1 codex distday-hold-rule -DryRun      # preview the command
./run_pipeline.ps1 codex distday-hold-rule -Sandbox read-only
./run_pipeline.ps1 codex distday-hold-rule -CodexModel gpt-5.5 -CodexReasoningEffort xhigh

# anytime: progress across all tasks
./run_pipeline.ps1 status
```

## Undo / checkpoints (`checkpoint.ps1`)

A code "memory point" you can roll back to if you don't like an agent's result.
`run_pipeline.ps1 codex <task>` automatically takes a checkpoint **before** Codex
runs, so an unwanted change is always reversible.

Snapshots capture the whole working tree (tracked + untracked, respecting
`.gitignore`) into a private git ref chain (`refs/checkpoints/auto`). This is
**isolated from your branch and commit history** — it never creates branch
commits and coexists with the external auto-commit script.

```powershell
./checkpoint.ps1 list             # newest first; index 0 = latest
./checkpoint.ps1 save "label"     # manual snapshot
./checkpoint.ps1 diff 2           # what differs between now and 2 checkpoints ago
./checkpoint.ps1 rollback 2       # restore the tree to 2 checkpoints ago
./checkpoint.ps1 rollback 0       # undo the last rollback
```

`rollback <n>` first auto-snapshots the current state, so **nothing is ever
lost** — `rollback 0` always brings back the pre-rollback state. Handles added,
modified, and deleted files. Ignored paths (`.venv`, `node_modules`) are left
untouched.

## Two modes

**Discuss a topic** — a roundtable of **claude + gemini + codex + you**.
**Change code** — research (a Gemini deep-research report *or* a roundtable
transcript) → claude synthesis → codex implementation.

```
DISCUSS                              CHANGE CODE
claude ┐                             Gemini deep research ┐
gemini ┼─ multi-round debate          OR roundtable result ┼─▶ claude ─▶ codex
codex  ┤   + your turn each round      (1-research.md)          (plan)  (build)
you    ┘   ─▶ transcript ──────────────────┘
```

The roundtable transcript can be fed straight into the change-code pipeline as
the research input (see `-Research` below).

## Project debate (`discuss.ps1`)

A multi-round roundtable. The three agents argue a topic about this repo and see
each other's points in later rounds; **you are a participant too** — after the
agents respond each round you get a turn to react/steer, and the agents weigh
your input in the next round. Output is one transcript; you then ask the
interactive Claude Code session to synthesize it (it has context the headless
agents lack).

Transcript contributions are concise Traditional Chinese summaries. Each seat
uses `立場 / 理由 / 建議`, with `共識狀態` added when consensus mode is enabled.

```powershell
# when already inside Docs/research-pipeline/
./discuss.ps1 "Should the survivorship backfill be on by default?" -Rounds 2
./discuss.ps1 "Topic..." -NoHuman      # agent-only debate (no human turn)
./discuss.ps1 "Topic..." -Yes          # skip the cost confirmation
./discuss.ps1 "Topic..." -DryRun       # show model profile; no billed calls
./discuss.ps1 "Topic..." -Rounds 2 -UntilConsensus -MaxRounds 6
# then, in Claude Code:  "synthesize the discussion <printed path>"
```

From the repository root, prefix the script path:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Docs\research-pipeline\discuss.ps1 "Topic..." -Rounds 2 -UntilConsensus -MaxRounds 6
```

- Quality defaults: Claude `opus` with `high` effort, Gemini
  `gemini-3-flash-preview` (with `gemini-2.5-flash` fallback), and Codex
  `gpt-5.5` with `high` reasoning.
  Override with `-ClaudeModel`, `-ClaudeEffort`, `-GeminiModel`,
  `-GeminiFallbackModels`, `-CodexModel`, or `-CodexReasoningEffort`.
  `gemini-3.5-flash` returned `ModelNotFoundError` through the currently
  authenticated local Gemini CLI on 2026-05-26, so it is not the default.
- Light role nudges keep the voices distinct: claude = correctness/architecture,
  gemini = alternatives/research, codex = implementation feasibility.
- Codex always runs `--sandbox read-only` — a discussion never edits code.
- Claude and Gemini are invoked from the repository root and restricted to
  read-only verification during discussion; tool/CLI stderr is not treated as
  their debate content.
- Consensus mode continues after the minimum round count until all participating
  agents explicitly emit `CONSENSUS_STATUS: AGREE` in the same round and the
  human adds no new steer. Always set `-MaxRounds` as a cost guard; if agreement
  is not reached, the transcript records unresolved consensus rather than
  pretending there is a decision.
- Cost/time: ~`agents × rounds` billed calls, each 30s–2min; confirms before
  running (skip with `-Yes`). Transcripts land in `discussions/`.

## Feeding research into the change-code pipeline

Stage 1 (`1-research.md`) accepts **either** source — seed it from a file with
`-Research`:

```powershell
# from a Gemini deep-research report you saved:
./run_pipeline.ps1 new my-task "title" -Research C:\path\to\gemini-report.md
# or straight from a roundtable transcript:
./run_pipeline.ps1 new my-task "title" -Research .\discussions\<transcript>.md
```

Then ask Claude Code to fill `2-plan.md` + `3-codex-prompt.md`, review, and run
`./run_pipeline.ps1 codex my-task`.

## Guardrails

The Codex leg always prepends
`Docs/agent-prompts/canslim/CODEX_CANSLIM_GUARDRAILS.md` so every implementation
inherits the anti-overfit / additive-only / no-action-verb rules. Do **not**
copy guardrails into `3-codex-prompt.md` — the runner adds them.

## Why checkpoints (not full auto)

- Stage 1→2: Gemini reports evidence and hypotheses in a fixed format; research
  can still be wrong or already implemented, so Claude verifies claims against
  the repo before any Codex contract is written.
- Stage 2→3: you approve scope and the exact file changes before Codex touches
  the tree — the prompt is the contract.
- Stage 3→done: Codex's summary describes intent, not what landed. Always read
  `git diff` before committing.
