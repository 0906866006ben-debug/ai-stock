<#
.SYNOPSIS
  Root shortcut for the roundtable debate (claude + gemini + codex + you).
  Forwards everything to Docs\research-pipeline\discuss.ps1.

.EXAMPLE
  .\discuss.ps1 "Should the survivorship backfill be on by default?" -Rounds 2
  .\discuss.ps1 "topic..." -NoHuman -Yes
#>
& "$PSScriptRoot\Docs\research-pipeline\discuss.ps1" @args
