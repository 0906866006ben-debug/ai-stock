# Waits for currently running backfill processes to finish, then launches the
# full-universe (508-symbol) backfill in 2 shards. Temporary operational script.
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
$Py = Join-Path $Root ".venv\Scripts\python.exe"
$Log = Join-Path $Root "backend\data\research_platform\logs"

while ($true) {
    $procs = Get-CimInstance Win32_Process | Where-Object {
        $_.Name -eq 'python.exe' -and $_.CommandLine -match '_backfill_runner'
    }
    if (-not $procs) { break }
    Start-Sleep -Seconds 120
}

foreach ($i in 0, 1) {
    Start-Process -FilePath $Py `
        -ArgumentList "backend\data\research_platform\_backfill_runner.py", "$i", "2" `
        -WorkingDirectory $Root `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $Log "backfill-full-shard$i.out.log") `
        -RedirectStandardError (Join-Path $Log "backfill-full-shard$i.err.log")
}
