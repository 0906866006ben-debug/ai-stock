param(
    [switch]$NoBrowser,
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$frontendDir = Join-Path $repoRoot "ai-stock-frontend"
$backendPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
$backendUrl = "http://localhost:8000"
$frontendUrl = "http://localhost:3000"

function Resolve-NpmCmd {
    $npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if ($npm) {
        return $npm.Source
    }

    $nodePath = "C:\Program Files\nodejs"
    $npmPath = Join-Path $nodePath "npm.cmd"
    if (Test-Path -LiteralPath $npmPath) {
        $env:Path = "$env:Path;$nodePath"
        return $npmPath
    }

    throw "npm.cmd was not found. Install Node.js LTS, then reopen PowerShell."
}

function Test-PortInUse([int]$Port) {
    $connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if (-not $connections) {
        return $false
    }

    foreach ($connection in $connections) {
        $owningProcess = $connection.OwningProcess
        if (-not $owningProcess -or $owningProcess -le 0) {
            continue
        }

        $process = Get-Process -Id $owningProcess -ErrorAction SilentlyContinue
        if ($process) {
            return $true
        }
    }

    return $false
}

function Start-DevWindow([string]$Title, [string]$WorkingDirectory, [string]$Command) {
    $escapedTitle = $Title.Replace("'", "''")
    $escapedWorkingDirectory = $WorkingDirectory.Replace("'", "''")
    $windowCommand = @"
`$Host.UI.RawUI.WindowTitle = '$escapedTitle'
Set-Location -LiteralPath '$escapedWorkingDirectory'
$Command
"@

    Start-Process powershell.exe -WorkingDirectory $WorkingDirectory -ArgumentList @(
        "-NoExit",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        $windowCommand
    )
}

function Start-CmdWindow([string]$Title, [string]$WorkingDirectory, [string]$Command) {
    $cmdCommand = "title $Title && cd /d `"$WorkingDirectory`" && $Command"
    Start-Process cmd.exe -WorkingDirectory $WorkingDirectory -ArgumentList @(
        "/k",
        $cmdCommand
    )
}

function Wait-ForPort([int]$Port, [int]$TimeoutSeconds = 20) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-PortInUse $Port) {
            return $true
        }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

Write-Host "AI Stock dev launcher"
Write-Host "Repo: $repoRoot"

if (-not (Test-Path -LiteralPath $backendPython)) {
    throw "Backend Python was not found at $backendPython. Create the venv first or install backend dependencies."
}

if (-not (Test-Path -LiteralPath $frontendDir)) {
    throw "Frontend directory was not found at $frontendDir."
}

$npmCmd = Resolve-NpmCmd

if (-not (Test-Path -LiteralPath (Join-Path $frontendDir "node_modules"))) {
    Write-Warning "Frontend node_modules is missing. Run: cd ai-stock-frontend; npm.cmd install"
}

Write-Host "Backend Python: $backendPython"
Write-Host "npm: $npmCmd"

if ($CheckOnly) {
    Write-Host "Check only completed. No services were started."
    exit 0
}

if (Test-PortInUse 8000) {
    Write-Host "Backend port 8000 is already in use. Reusing existing backend."
}
else {
    Start-DevWindow `
        -Title "AI Stock Backend :8000" `
        -WorkingDirectory $repoRoot `
        -Command "& `"$backendPython`" -m uvicorn backend.app.main:app --reload --port 8000"
    if (Wait-ForPort 8000) {
        Write-Host "Backend starting at $backendUrl"
    }
    else {
        Write-Warning "Backend window was opened, but port 8000 did not come up within the expected time."
    }
}

if (Test-PortInUse 3000) {
    Write-Host "Frontend port 3000 is already in use. Reusing existing frontend."
}
else {
    Start-CmdWindow `
        -Title "AI Stock Frontend :3000" `
        -WorkingDirectory $frontendDir `
        -Command "set `"NEXT_PUBLIC_API_URL=$backendUrl`" && `"$npmCmd`" run dev"
    if (Wait-ForPort 3000) {
        Write-Host "Frontend starting at $frontendUrl"
    }
    else {
        Write-Warning "Frontend window was opened, but port 3000 did not come up within the expected time."
    }
}

if (-not $NoBrowser) {
    Start-Sleep -Seconds 3
    Start-Process $frontendUrl
}

Write-Host "Done. Backend: $backendUrl | Frontend: $frontendUrl"
