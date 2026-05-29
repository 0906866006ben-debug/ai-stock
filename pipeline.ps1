<#
.SYNOPSIS
  Root shortcut for the change-code pipeline (research -> claude plan -> codex).
  Forwards everything to Docs\research-pipeline\run_pipeline.ps1.

.EXAMPLE
  .\pipeline.ps1 status
  .\pipeline.ps1 new my-task "title" -Research C:\temp\research.md
  .\pipeline.ps1 new my-task "title" -Research .\Docs\research-pipeline\discussions\<transcript>.md
  .\pipeline.ps1 codex my-task
#>
& "$PSScriptRoot\Docs\research-pipeline\run_pipeline.ps1" @args
