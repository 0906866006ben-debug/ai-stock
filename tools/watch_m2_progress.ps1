param(
    [string]$LogPath = "artifacts\canslim_m2_broad_fundamentals\download_fundamentals_broad_all5_20260522_094718.err.log",
    [string]$DbPath = "backend\pit_fundamentals.db",
    [int]$TotalJobs = 5775,
    [int]$RefreshSeconds = 20
)

$ErrorActionPreference = "SilentlyContinue"

function Get-LatestJob {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        return @{ Current = 0; Text = "waiting for log..." }
    }
    $line = Get-Content $Path -Tail 300 |
        Select-String -Pattern "\((\d+)/(\d+)\)" |
        Select-Object -Last 1
    if (-not $line) {
        return @{ Current = 0; Text = "starting..." }
    }
    $m = [regex]::Match($line.Line, "\((\d+)/(\d+)\)")
    return @{ Current = [int]$m.Groups[1].Value; Text = $line.Line }
}

function Get-DbCounts {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        return ""
    }
    $py = @"
import sqlite3
conn = sqlite3.connect(r"$Path")
for t in ["month_revenue","institutional","margin","per","financials"]:
    r = conn.execute(f"select count(*) from {t}").fetchone()[0]
    s = conn.execute(f"select count(distinct stock_id) from {t}").fetchone()[0]
    col = "period_end" if t == "financials" else "date"
    mn = conn.execute(f"select min({col}) from {t}").fetchone()[0]
    print(f"{t}: rows={r:,} symbols={s} earliest={mn}")
conn.close()
"@
    return (& .venv\Scripts\python -c $py) -join "`n"
}

while ($true) {
    $job = Get-LatestJob -Path $LogPath
    $current = [math]::Min($job.Current, $TotalJobs)
    $pct = if ($TotalJobs -gt 0) { [math]::Round(($current / $TotalJobs) * 100, 1) } else { 0 }

    Clear-Host
    Write-Progress -Activity "M2 broad PIT fundamentals backfill" -Status "$current / $TotalJobs ($pct%)" -PercentComplete $pct
    Write-Host "M2 broad PIT fundamentals backfill"
    Write-Host "Progress: $current / $TotalJobs ($pct%)"
    Write-Host "Log:      $LogPath"
    Write-Host ""
    Write-Host "Latest:"
    Write-Host $job.Text
    Write-Host ""
    Write-Host "Dataset counts:"
    Write-Host (Get-DbCounts -Path $DbPath)
    Write-Host ""
    Write-Host "Press Ctrl+C to stop watching. Download keeps running."

    Start-Sleep -Seconds $RefreshSeconds
}
