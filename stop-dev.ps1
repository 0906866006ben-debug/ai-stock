param()

$ErrorActionPreference = "Stop"

function Get-PortPids([int]$Port) {
    $connections = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
    if (-not $connections) {
        return @()
    }

    return @(
        $connections |
        Select-Object -ExpandProperty OwningProcess |
        Where-Object { $_ -and $_ -gt 0 } |
        Sort-Object -Unique
    )
}

function Stop-PortProcesses([int]$Port) {
    for ($attempt = 1; $attempt -le 5; $attempt++) {
        $pids = Get-PortPids -Port $Port
        if (-not $pids -or $pids.Count -eq 0) {
            Write-Host "Port $Port is already clear."
            return
        }

        foreach ($processId in $pids) {
            try {
                $process = Get-Process -Id $processId -ErrorAction Stop
                Stop-Process -Id $processId -Force -ErrorAction Stop
                Write-Host "Stopped PID $processId ($($process.ProcessName)) on port $Port."
            }
            catch {
                Write-Warning "PID $processId on port $Port was already gone."
            }
        }

        Start-Sleep -Milliseconds 750
    }

    $remaining = Get-PortPids -Port $Port
    if ($remaining -and $remaining.Count -gt 0) {
        Write-Warning "Port $Port still has listeners after retries: $($remaining -join ', ')"
    }
    else {
        Write-Host "Port $Port is already clear."
    }
}

Write-Host "Stopping AI Stock dev services..."
Stop-PortProcesses -Port 8000
Stop-PortProcesses -Port 3000
Write-Host "Done."
