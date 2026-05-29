<#
.SYNOPSIS
  Checkpointed research -> synthesis -> implementation pipeline runner.

  Three stages, with a human checkpoint between each (see README.md):
    1. Research    (Gemini deep research)  -> 1-research.md   [manual paste]
    2. Synthesis   (Claude Code session)   -> 2-plan.md + 3-codex-prompt.md
    3. Implementation (Codex CLI)          -> automated by this script

  Only the Codex leg is scriptable today (gemini/claude CLIs are not installed
  headless on this machine). This runner scaffolds task folders, reports status,
  and runs Codex non-interactively with the guardrails doc prepended.

.EXAMPLE
  # 1. scaffold a task folder from the template
  ./run_pipeline.ps1 new distday-hold-rule "TW hold-period calibration"

  # 2. (paste Gemini report into 1-research.md, then ask Claude Code to fill
  #     2-plan.md and 3-codex-prompt.md — review them)

  # 3. run the Codex implementation leg
  ./run_pipeline.ps1 codex distday-hold-rule

  # any time: see where each task stands
  ./run_pipeline.ps1 status
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)][ValidateSet('new', 'status', 'codex')] [string]$Command = 'status',
    [Parameter(Position = 1)][string]$Task,
    [Parameter(Position = 2)][string]$Title,
    # Codex sandbox: read-only | workspace-write | danger-full-access
    [string]$Sandbox = 'workspace-write',
    [string]$CodexModel = 'gpt-5.5',
    [ValidateSet('low', 'medium', 'high', 'xhigh')][string]$CodexReasoningEffort = 'high',
    # Show what would run without invoking Codex
    [switch]$DryRun,
    # Seed 1-research.md from a file: a Gemini deep-research report OR a discuss.ps1 transcript
    [string]$Research
)

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
. (Join-Path $Root 'agent_log.ps1')   # Write-AgentEvent for the dashboard (best-effort)
$TasksDir = Join-Path $Root 'tasks'
$TemplateDir = Join-Path $Root '_template'
# Repo root is two levels up from Docs/research-pipeline
$RepoRoot = (Resolve-Path (Join-Path $Root '..\..')).Path
$Guardrails = Join-Path $RepoRoot 'Docs\agent-prompts\canslim\CODEX_CANSLIM_GUARDRAILS.md'

function Get-TaskDir([string]$name) {
    if (-not $name) { throw "Task id required. Usage: run_pipeline.ps1 $Command <task-id>" }
    return Join-Path $TasksDir $name
}

function Invoke-New {
    $dir = Get-TaskDir $Task
    if (Test-Path $dir) { throw "Task '$Task' already exists at $dir" }
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
    Get-ChildItem $TemplateDir -File | ForEach-Object {
        Copy-Item $_.FullName (Join-Path $dir $_.Name)
    }
    if ($Title) { Set-Content (Join-Path $dir 'TITLE.txt') $Title -Encoding utf8 }

    # Stage 1 input can be EITHER a Gemini deep-research report OR a discussion
    # transcript (discuss.ps1). If given, seed 1-research.md from it.
    if ($Research) {
        if (-not (Test-Path $Research)) { throw "Research file not found: $Research" }
        $src = (Resolve-Path $Research).Path
        $hdr = "<!-- Stage 1 seeded from: $src on $(Get-Date -Format 'yyyy-MM-dd HH:mm') -->`n`n"
        [System.IO.File]::WriteAllText((Join-Path $dir '1-research.md'), $hdr + (Get-Content $src -Raw), (New-Object System.Text.UTF8Encoding($false)))
        Write-Host "Created task '$Task' at $dir (1-research.md seeded from $src)" -ForegroundColor Green
        Write-Host "Next: ask Claude Code to fill 2-plan.md + 3-codex-prompt.md from the research, then: run_pipeline.ps1 codex $Task"
        return
    }

    Write-Host "Created task '$Task' at $dir" -ForegroundColor Green
    Write-Host "Next: put a Gemini report OR a discuss.ps1 transcript into 1-research.md"
    Write-Host "      (or re-create with -Research <file>), then ask Claude Code to fill 2-plan.md + 3-codex-prompt.md."
}

function Get-MeaningfulText([string]$path) {
    # Non-blank lines, trimmed — the comparable "content" of a stage file.
    if (-not (Test-Path $path)) { return '' }
    return ((Get-Content $path | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne '' }) -join "`n")
}

function Test-Filled([string]$path) {
    # "filled" = exists AND differs from the pristine template of the same name.
    if (-not (Test-Path $path)) { return $false }
    $tmpl = Join-Path $TemplateDir (Split-Path $path -Leaf)
    return (Get-MeaningfulText $path) -ne (Get-MeaningfulText $tmpl)
}

function Invoke-Status {
    if (-not (Test-Path $TasksDir)) { Write-Host "No tasks yet. Create one: run_pipeline.ps1 new <task-id>"; return }
    $tasks = Get-ChildItem $TasksDir -Directory | Sort-Object Name
    if (-not $tasks) { Write-Host "No tasks yet. Create one: run_pipeline.ps1 new <task-id>"; return }
    foreach ($t in $tasks) {
        $r = if (Test-Filled (Join-Path $t.FullName '1-research.md')) { '[x]' } else { '[ ]' }
        $p = if (Test-Filled (Join-Path $t.FullName '2-plan.md')) { '[x]' } else { '[ ]' }
        $c = if (Test-Filled (Join-Path $t.FullName '3-codex-prompt.md')) { '[x]' } else { '[ ]' }
        $done = Test-Path (Join-Path $t.FullName 'codex-last-message.md')
        $run = if ($done) { '[x]' } else { '[ ]' }
        Write-Host ("{0,-28} research{1} plan{2} prompt{3} codex-run{4}" -f $t.Name, $r, $p, $c, $run)
    }
}

function Invoke-Codex {
    $dir = Get-TaskDir $Task
    if (-not (Test-Path $dir)) { throw "Task '$Task' not found. Scaffold it first: run_pipeline.ps1 new $Task" }
    $promptFile = Join-Path $dir '3-codex-prompt.md'
    if (-not (Test-Filled $promptFile)) { throw "3-codex-prompt.md is empty/unfilled. Have Claude Code write it (and review it) first." }

    # Compose: guardrails (if present) + the task prompt.
    $composed = ''
    if (Test-Path $Guardrails) {
        $composed += (Get-Content $Guardrails -Raw) + "`n`n---`n`n"
    } else {
        Write-Warning "Guardrails doc not found at $Guardrails — running prompt without it."
    }
    $composed += (Get-Content $promptFile -Raw)

    $composedFile = Join-Path $dir 'codex-composed-prompt.md'
    $composed | Set-Content $composedFile -Encoding utf8
    $lastMsg = Join-Path $dir 'codex-last-message.md'

    Write-Host "Codex implementation leg for '$Task'" -ForegroundColor Cyan
    Write-Host "  prompt:   $promptFile (+ guardrails prepended)"
    Write-Host "  cwd:      $RepoRoot"
    Write-Host "  sandbox:  $Sandbox"
    Write-Host "  model:    $CodexModel (reasoning=$CodexReasoningEffort)"
    Write-Host "  output:   $lastMsg"

    if ($DryRun) {
        Write-Host "[dry-run] would run: Get-Content '$composedFile' | codex exec --cd '$RepoRoot' --sandbox $Sandbox -m '$CodexModel' -c 'model_reasoning_effort=`"$CodexReasoningEffort`"' -o '$lastMsg'" -ForegroundColor Yellow
        return
    }

    $codexCmd = Join-Path $env:APPDATA 'npm\codex.cmd'
    if (-not (Test-Path $codexCmd)) {
        $resolvedCmd = Get-Command 'codex.cmd' -ErrorAction SilentlyContinue
        if ($resolvedCmd) { $codexCmd = $resolvedCmd.Source }
    }
    if (-not (Test-Path $codexCmd)) {
        throw "codex CLI not found on PATH. Install it, or run 3-codex-prompt.md by hand."
    }

    # Auto-checkpoint the working tree BEFORE Codex touches it, so a result you
    # don't like can be undone with: checkpoint.ps1 rollback <n>
    $ckpt = Join-Path $Root 'checkpoint.ps1'
    if (Test-Path $ckpt) {
        & $ckpt save "before codex: $Task"
    } else {
        Write-Warning "checkpoint.ps1 not found — running Codex without a pre-action snapshot."
    }

    $reasoningConfig = 'model_reasoning_effort="{0}"' -f $CodexReasoningEffort
    $RunId = New-AgentRunId
    Write-AgentEvent -Agent codex-impl -Role implementation -Event start -Task $Task -RunId $RunId
    Get-Content $composedFile -Raw | & $codexCmd exec --cd $RepoRoot --sandbox $Sandbox -m $CodexModel -c $reasoningConfig -o $lastMsg
    Write-AgentEvent -Agent codex-impl -Role implementation -Event end -Task $Task -RunId $RunId -Out $lastMsg
    Write-Host ""
    Write-Host "Codex finished. CHECKPOINT — review the diff before committing:" -ForegroundColor Green
    Write-Host "  git -C `"$RepoRoot`" status; git -C `"$RepoRoot`" diff"
    Write-Host "  final message: $lastMsg"
    Write-Host "  don't like it? undo: ./checkpoint.ps1 rollback 0   (snapshot was taken before this run)"
}

switch ($Command) {
    'new' { Invoke-New }
    'status' { Invoke-Status }
    'codex' { Invoke-Codex }
}
