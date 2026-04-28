<#
.SYNOPSIS
  Stop the kabu-relay process started by Start-Relay.ps1.
#>

$ErrorActionPreference = 'SilentlyContinue'
$root = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $root 'data\relay.pid'
$port = 18091

$stopped = $false

if (Test-Path $pidFile) {
    $relayPid = (Get-Content $pidFile -Raw).Trim()
    if ($relayPid -match '^\d+$') {
        $proc = Get-Process -Id $relayPid -ErrorAction SilentlyContinue
        if ($proc) {
            # Use taskkill /T to kill the whole process tree — the .venv shim
            # spawns a child python.exe, and Windows does not auto-kill children
            # when the parent dies, so a plain Stop-Process on the wrapper PID
            # leaves the listener orphaned but alive.
            $null = & taskkill.exe /F /T /PID $relayPid 2>&1
            Write-Output "stopped PID=$relayPid + children (from relay.pid)"
            $stopped = $true
        }
    }
    Remove-Item $pidFile -ErrorAction SilentlyContinue
}

# Fallback: kill anything still listening on the port.
$conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($conn) {
    foreach ($c in $conn) {
        try {
            Stop-Process -Id $c.OwningProcess -Force
            Write-Output "stopped PID=$($c.OwningProcess) (was holding port $port)"
            $stopped = $true
        } catch {}
    }
}

if (-not $stopped) {
    Write-Output "relay was not running"
}
