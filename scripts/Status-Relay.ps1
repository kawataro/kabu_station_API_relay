<#
.SYNOPSIS
  Quick status check for the kabu-relay.
#>

$ErrorActionPreference = 'SilentlyContinue'
$root = Split-Path -Parent $PSScriptRoot
$port = 18091
$pidFile = Join-Path $root 'data\relay.pid'

$conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($conn) {
    $relayPid = $conn.OwningProcess | Select-Object -First 1
    $proc = Get-Process -Id $relayPid -ErrorAction SilentlyContinue
    if ($proc) {
        $uptime = (Get-Date) - $proc.StartTime
        Write-Output ("UP  PID={0}  port={1}  uptime={2:N0}s  cpu={3:N1}s  ws={4:N0}MB" -f `
            $relayPid, $port, $uptime.TotalSeconds, $proc.CPU, ($proc.WorkingSet64 / 1MB))
    } else {
        Write-Output "UP  port=$port  (PID lookup failed)"
    }
    Write-Output ""
    Write-Output "--- /health ---"
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$port/health" -TimeoutSec 3 -UseBasicParsing
        Write-Output "HTTP $($r.StatusCode): $($r.Content)"
    } catch {
        Write-Output "fetch failed: $($_.Exception.Message)"
    }
} else {
    Write-Output "DOWN  (nothing listening on $port)"
    if (Test-Path $pidFile) {
        Write-Output "  stale relay.pid found; remove with:  Remove-Item $pidFile"
    }
}
