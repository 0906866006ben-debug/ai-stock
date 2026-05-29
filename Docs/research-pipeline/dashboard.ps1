<#
.SYNOPSIS
  Terminal dashboard for the 6-agent pipeline. Shows live status + history by
  reading runs/events.jsonl (emitted by discuss/research/run_pipeline) and the
  pipeline task folders. Read-only; never calls any agent.

  Six agents:
    roundtable     : claude, gemini, codex        (discuss.ps1)
    research       : gemini-research              (research.ps1)
    synthesis      : claude-synth                 (derived from 2-plan.md state)
    implementation : codex-impl                   (run_pipeline.ps1 codex leg)

.EXAMPLE
  ./dashboard.ps1                 # live, auto-refresh every 3s (Ctrl+C to quit)
  ./dashboard.ps1 -Once           # render a single snapshot and exit
  ./dashboard.ps1 -Interval 5 -History 20
#>
[CmdletBinding()]
param(
    [int]$Interval = 3,
    [switch]$Once,
    [int]$History = 12
)

$Root = $PSScriptRoot
$EventsFile = Join-Path $Root 'runs\events.jsonl'
$TasksDir = Join-Path $Root 'tasks'
$TemplateDir = Join-Path $Root '_template'

# Fixed display order so even never-seen agents show as idle.
$AgentRows = @(
    @{ role = 'roundtable'; agent = 'claude' },
    @{ role = 'roundtable'; agent = 'gemini' },
    @{ role = 'roundtable'; agent = 'codex' },
    @{ role = 'research'; agent = 'gemini-research' },
    @{ role = 'synthesis'; agent = 'claude-synth' },
    @{ role = 'implementation'; agent = 'codex-impl' }
)

function Read-Events {
    if (-not (Test-Path $EventsFile)) { return @() }
    $events = [System.Collections.Generic.List[object]]::new()
    foreach ($line in (Get-Content $EventsFile -Tail 3000 -ErrorAction SilentlyContinue)) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        try {
            $o = $line | ConvertFrom-Json
            $o | Add-Member -NotePropertyName _ts -NotePropertyValue ([datetime]$o.ts) -Force
            $events.Add($o)
        } catch { }
    }
    return $events
}

function Rel([datetime]$t) {
    $s = [int]((Get-Date) - $t).TotalSeconds
    if ($s -lt 0) { $s = 0 }
    if ($s -lt 60) { return "${s}s ago" }
    if ($s -lt 3600) { return "$([int]($s/60))m ago" }
    if ($s -lt 86400) { return "$([int]($s/3600))h ago" }
    return "$([int]($s/86400))d ago"
}

function Get-MeaningfulText([string]$path) {
    if (-not (Test-Path $path)) { return '' }
    return ((Get-Content $path | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne '' }) -join "`n")
}
function Test-Filled([string]$path) {
    if (-not (Test-Path $path)) { return $false }
    $tmpl = Join-Path $TemplateDir (Split-Path $path -Leaf)
    return (Get-MeaningfulText $path) -ne (Get-MeaningfulText $tmpl)
}

function Get-SynthState {
    # claude-synth is the interactive Claude Code session — not event-emitting.
    # Derive its activity from the most recently filled 2-plan.md across tasks.
    if (-not (Test-Path $TasksDir)) { return $null }
    $latest = $null
    foreach ($t in (Get-ChildItem $TasksDir -Directory -ErrorAction SilentlyContinue)) {
        $plan = Join-Path $t.FullName '2-plan.md'
        if (Test-Filled $plan) {
            $mt = (Get-Item $plan).LastWriteTime
            if (-not $latest -or $mt -gt $latest.time) { $latest = @{ time = $mt; task = $t.Name } }
        }
    }
    return $latest
}

function Write-Cell([string]$text, [int]$width, [string]$color) {
    if ($text.Length -gt $width) { $text = $text.Substring(0, $width - 1) + '…' }
    Write-Host ($text.PadRight($width)) -ForegroundColor $color -NoNewline
}

function Render {
    $events = Read-Events
    $latestByAgent = @{}
    foreach ($e in $events) {
        if (-not $latestByAgent.ContainsKey($e.agent) -or $e._ts -gt $latestByAgent[$e.agent]._ts) {
            $latestByAgent[$e.agent] = $e
        }
    }
    $synth = Get-SynthState

    Clear-Host
    Write-Host ("AGENT PIPELINE DASHBOARD".PadRight(52)) -ForegroundColor White -NoNewline
    Write-Host ("{0}  (refresh {1}s, Ctrl+C quit)" -f (Get-Date -Format 'HH:mm:ss'), $Interval) -ForegroundColor DarkGray
    Write-Host ("-" * 78) -ForegroundColor DarkGray

    # ── Live status ──
    Write-Host "LIVE STATUS" -ForegroundColor Cyan
    Write-Cell "ROLE" 16 'DarkGray'; Write-Cell "AGENT" 17 'DarkGray'; Write-Cell "STATE" 9 'DarkGray'; Write-Cell "TASK" 24 'DarkGray'; Write-Host "WHEN" -ForegroundColor DarkGray
    foreach ($row in $AgentRows) {
        $agent = $row.agent
        $state = 'idle'; $stColor = 'DarkGray'; $task = '-'; $when = '-'
        if ($agent -eq 'claude-synth') {
            $ev = $latestByAgent[$agent]
            if ($ev -and $ev._ts -gt ($synth.time)) {
                $state = $ev.status; $task = "$($ev.task)"; $when = Rel $ev._ts
                $stColor = if ($ev.event -eq 'start') { 'Green' } elseif ($ev.event -eq 'error') { 'Red' } else { 'Cyan' }
            } elseif ($synth) {
                $state = 'last'; $stColor = 'Cyan'; $task = $synth.task; $when = Rel $synth.time
            }
        } elseif ($latestByAgent.ContainsKey($agent)) {
            $ev = $latestByAgent[$agent]
            $task = "$($ev.task)"; if ($ev.round) { $task = "$task (r$($ev.round))" }
            $when = Rel $ev._ts
            switch ($ev.event) {
                'start' { $state = 'RUNNING'; $stColor = 'Green' }
                'end' { $state = 'done'; $stColor = 'Cyan' }
                'error' { $state = 'ERROR'; $stColor = 'Red' }
            }
        }
        Write-Cell $row.role 16 'Gray'; Write-Cell $agent 17 'White'; Write-Cell $state 9 $stColor; Write-Cell $task 24 'Gray'; Write-Host $when -ForegroundColor DarkGray
    }

    # ── Pipeline tasks ──
    Write-Host ""
    Write-Host "PIPELINE TASKS" -ForegroundColor Cyan
    if (Test-Path $TasksDir) {
        $tasks = Get-ChildItem $TasksDir -Directory -ErrorAction SilentlyContinue | Sort-Object Name
        if ($tasks) {
            foreach ($t in $tasks) {
                $r = if (Test-Filled (Join-Path $t.FullName '1-research.md')) { 'x' } else { ' ' }
                $p = if (Test-Filled (Join-Path $t.FullName '2-plan.md')) { 'x' } else { ' ' }
                $c = if (Test-Filled (Join-Path $t.FullName '3-codex-prompt.md')) { 'x' } else { ' ' }
                $run = if (Test-Path (Join-Path $t.FullName 'codex-last-message.md')) { 'x' } else { ' ' }
                Write-Cell $t.Name 28 'White'
                Write-Host ("research[{0}] plan[{1}] prompt[{2}] codex-run[{3}]" -f $r, $p, $c, $run) -ForegroundColor Gray
            }
        } else { Write-Host "  (no tasks yet)" -ForegroundColor DarkGray }
    } else { Write-Host "  (no tasks yet)" -ForegroundColor DarkGray }

    # ── Recent events ──
    Write-Host ""
    Write-Host ("RECENT EVENTS (last {0})" -f $History) -ForegroundColor Cyan
    $recent = $events | Select-Object -Last $History
    if (-not $recent) { Write-Host "  (no events logged yet — run discuss/research/pipeline)" -ForegroundColor DarkGray }
    foreach ($e in $recent) {
        $col = switch ($e.event) { 'start' { 'Green' } 'end' { 'Cyan' } 'error' { 'Red' } default { 'Gray' } }
        $info = if ($e.out) { $e.out } else { $e.detail }
        Write-Host ("  {0}  " -f $e._ts.ToString('HH:mm:ss')) -ForegroundColor DarkGray -NoNewline
        Write-Cell $e.agent 16 'White'; Write-Cell $e.event 7 $col; Write-Cell "$($e.task)" 22 'Gray'; Write-Host "$info" -ForegroundColor DarkGray
    }
}

if ($Once) { Render; return }
try {
    while ($true) { Render; Start-Sleep -Seconds $Interval }
} finally {
    Write-Host "`nDashboard stopped." -ForegroundColor DarkGray
}
