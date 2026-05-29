<#
.SYNOPSIS
  Run a Gemini CLI research pass on a topic and save a structured report file
  that you can feed straight into the change-code pipeline (pipeline.ps1 -Research).

  NOTE: this is the Gemini *CLI* (agentic chat + web tools), NOT the web app's
  "Deep Research" mode (that lives at gemini.google.com and uses your Pro
  subscription). For the deepest reports, run it there and save the export as a
  .md file instead — then pass that file to pipeline.ps1 -Research.

.EXAMPLE
  .\research.ps1 "Is O'Neil's 8-week hold rule valid for TW semiconductor cycles?"
  .\research.ps1 "topic..." -Out C:\temp\my-research.md
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0, Mandatory = $true)][string]$Topic,
    [string]$Out
)

# Native CLI stderr (256-color / ripgrep warnings) must not terminate the script.
$ErrorActionPreference = 'Continue'
. (Join-Path $PSScriptRoot 'Docs\research-pipeline\agent_log.ps1')   # dashboard events (best-effort)
$RunId = New-AgentRunId

$gemini = (Get-Command gemini -ErrorAction SilentlyContinue).Source
if (-not $gemini) {
    foreach ($p in @("$env:APPDATA\npm\gemini.cmd", "$env:APPDATA\npm\gemini.ps1")) { if (Test-Path $p) { $gemini = $p; break } }
}
if (-not $gemini) { throw "gemini CLI not found on PATH. Install @google/gemini-cli." }

$prompt = @"
You are a research assistant for the 'ai-stock' Taiwan CAN SLIM stock-screener repo.
Research the topic below and produce a STRUCTURED report in Markdown with these sections:
  ## Key findings
  ## Evidence / sources (with links where possible)
  ## Trade-offs and risks
  ## Concrete recommendation for this project
Be specific and cite sources. Do NOT modify any files.

TOPIC:
$Topic
"@

Write-Host "Running Gemini CLI research on: $Topic" -ForegroundColor Cyan
Write-Host "(this is the CLI, not the web Deep Research mode; may take 1-3 min)"

Write-AgentEvent -Agent gemini-research -Role research -Event start -Task $Topic -RunId $RunId
$raw = & $gemini --skip-trust -p $prompt 2>$null
$report = (($raw | Where-Object { $_ -notmatch 'Ripgrep is not available|256-color' }) -join "`n").Trim()

if ([string]::IsNullOrWhiteSpace($report)) {
    Write-AgentEvent -Agent gemini-research -Role research -Event error -Task $Topic -RunId $RunId -Detail "no usable output"
    Write-Warning "Gemini returned no usable output. Check 'gemini' login (run: gemini)."
    exit 1
}

if (-not $Out) {
    $slug = ($Topic -replace '[^\w\- ]', '' -replace '\s+', '-').ToLower()
    if ($slug.Length -gt 50) { $slug = $slug.Substring(0, 50) }
    $dir = Join-Path $PSScriptRoot 'Docs\research-pipeline\research'
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
    $Out = Join-Path $dir ("{0}_{1}.md" -f (Get-Date -Format 'yyyyMMdd-HHmmss'), $slug)
}
$header = "# Gemini CLI research: $Topic`n`n_$(Get-Date -Format 'yyyy-MM-dd HH:mm') — Gemini CLI (not web Deep Research)_`n`n"
[System.IO.File]::WriteAllText($Out, $header + $report, (New-Object System.Text.UTF8Encoding($false)))

Write-AgentEvent -Agent gemini-research -Role research -Event end -Task $Topic -RunId $RunId -Out $Out
Write-Host "`nResearch report saved: $Out" -ForegroundColor Green
Write-Host "Feed it into the pipeline with:"
Write-Host "  .\pipeline.ps1 new <task-id> `"<title>`" -Research `"$Out`""
exit 0
