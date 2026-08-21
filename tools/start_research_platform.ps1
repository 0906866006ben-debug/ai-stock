param(
    [int]$ApiPort = 8000
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$DataDir = Join-Path $Root "backend\data\research_platform"
$LogDir = Join-Path $DataDir "logs"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python virtual environment was not found at $Python"
}

$envFile = Join-Path $Root "backend\.env"
$tokenConfigured = $false
if (Test-Path -LiteralPath $envFile) {
    $tokenConfigured = [bool](Select-String -LiteralPath $envFile -Pattern '^AI_STOCK_BACKEND_TOKEN=.+$' -Quiet)
}
if (-not $tokenConfigured -and -not $env:AI_STOCK_BACKEND_TOKEN) {
    throw "AI_STOCK_BACKEND_TOKEN must be configured before the research API can run persistently."
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$apiListener = Get-NetTCPConnection -LocalPort $ApiPort -State Listen -ErrorAction SilentlyContinue
if (-not $apiListener) {
    Start-Process -FilePath $Python `
        -ArgumentList '-m','uvicorn','backend.app.main:app','--host','127.0.0.1','--port',"$ApiPort" `
        -WorkingDirectory $Root `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $LogDir "research-api.out.log") `
        -RedirectStandardError (Join-Path $LogDir "research-api.err.log")
}

$workerCommand = [regex]::Escape("backend\scripts\research_orchestrator.py")
$worker = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match $workerCommand }
if (-not $worker) {
    Start-Process -FilePath $Python `
        -ArgumentList 'backend\scripts\research_orchestrator.py','--schedule-cycle' `
        -WorkingDirectory $Root `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $LogDir "research-worker.out.log") `
        -RedirectStandardError (Join-Path $LogDir "research-worker.err.log")
}

Write-Output "Research API: http://127.0.0.1:$ApiPort/api/v1/health"
Write-Output "Research worker: persistent queue enabled"

