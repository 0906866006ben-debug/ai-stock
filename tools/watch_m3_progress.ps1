param(
    [string]$OutputDir = "artifacts\canslim_multicycle",
    [int]$StartYear = 2011,
    [int]$EndYear = 2025,
    [int]$RefreshSeconds = 20
)

$ErrorActionPreference = "SilentlyContinue"

function Get-RunProcess {
    $items = Get-CimInstance Win32_Process -Filter "name = 'python.exe'" |
        Where-Object { $_.CommandLine -match "run_canslim_multicycle|canslim.multicycle" }
    return $items
}

function Get-YearRows {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        return 0
    }
    try {
        $lines = (Get-Content $Path | Measure-Object -Line).Lines
        return [math]::Max(0, $lines - 1)
    } catch {
        return 0
    }
}

while ($true) {
    $yearsDir = Join-Path $OutputDir "years"
    $years = @($StartYear..$EndYear)
    $completed = @()
    $tradeTotal = 0
    foreach ($year in $years) {
        $path = Join-Path $yearsDir "$year.csv"
        if (Test-Path $path) {
            $completed += $year
            $tradeTotal += Get-YearRows -Path $path
        }
    }

    $totalYears = $years.Count
    $doneYears = $completed.Count
    $pct = if ($totalYears -gt 0) { [math]::Round(($doneYears / $totalYears) * 100, 1) } else { 0 }
    $lastYear = if ($completed.Count -gt 0) { ($completed | Sort-Object | Select-Object -Last 1) } else { "none" }
    $nextYear = if ($doneYears -lt $totalYears) { $years[$doneYears] } else { "done" }
    $proc = @(Get-RunProcess)
    $runningText = if ($proc.Count -gt 0) { "running PID(s): " + (($proc | Select-Object -ExpandProperty ProcessId) -join ", ") } else { "not running" }

    Clear-Host
    Write-Progress -Activity "M3 CAN SLIM multicycle backtest" -Status "$doneYears / $totalYears years ($pct%)" -PercentComplete $pct
    Write-Host "M3 CAN SLIM multicycle backtest"
    Write-Host "Progress:      $doneYears / $totalYears years ($pct%)"
    Write-Host "Completed:     $($completed -join ', ')"
    Write-Host "Last year:     $lastYear"
    Write-Host "Next year:     $nextYear"
    Write-Host "Tagged trades: $tradeTotal"
    Write-Host "Process:       $runningText"
    Write-Host "Output dir:    $OutputDir"
    Write-Host ""
    if (Test-Path (Join-Path $OutputDir "multicycle_summary.json")) {
        Write-Host "Summary exists: multicycle_summary.json"
    }
    Write-Host "Press Ctrl+C to stop watching. The backtest keeps running."

    Start-Sleep -Seconds $RefreshSeconds
}
