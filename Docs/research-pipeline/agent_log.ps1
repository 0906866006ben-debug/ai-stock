<#
.SYNOPSIS
  Shared append-only event log for the agent pipeline. Dot-source this from
  discuss.ps1 / research.ps1 / run_pipeline.ps1, then call Write-AgentEvent.

  Events are JSON Lines in runs/events.jsonl. dashboard.ps1 reads them to render
  live status + history. Logging is best-effort: it must NEVER break an agent run,
  so every write is wrapped and swallows its own errors.
#>

$script:AgentRunsDir = Join-Path $PSScriptRoot 'runs'
$script:AgentEventsFile = Join-Path $script:AgentRunsDir 'events.jsonl'

function New-AgentRunId {
    return (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + ([guid]::NewGuid().ToString('N').Substring(0, 6))
}

function Write-AgentEvent {
    param(
        [Parameter(Mandatory = $true)][string]$Agent,   # claude|gemini|codex|gemini-research|codex-impl|claude-synth
        [Parameter(Mandatory = $true)][string]$Role,     # roundtable|research|synthesis|implementation
        [Parameter(Mandatory = $true)][ValidateSet('start', 'end', 'error')][string]$Event,
        [string]$Task = '',
        [int]$Round = 0,
        [string]$Detail = '',
        [string]$Out = '',
        [string]$RunId = ''
    )
    try {
        if (-not (Test-Path $script:AgentRunsDir)) {
            New-Item -ItemType Directory -Path $script:AgentRunsDir -Force | Out-Null
        }
        $status = switch ($Event) { 'start' { 'running' } 'end' { 'done' } 'error' { 'error' } }
        if ($Detail.Length -gt 240) { $Detail = $Detail.Substring(0, 240) }
        $obj = [ordered]@{
            ts     = (Get-Date).ToString('o')
            agent  = $Agent
            role   = $Role
            event  = $Event
            status = $status
            task   = $Task
            round  = $Round
            detail = $Detail
            out    = $Out
            run_id = $RunId
        }
        $line = ($obj | ConvertTo-Json -Compress -Depth 4)
        # Single-line guarantee (ConvertTo-Json -Compress already strips newlines).
        Add-Content -Path $script:AgentEventsFile -Value $line -Encoding utf8
    } catch {
        # Never let logging failures interrupt the agent run.
    }
}
