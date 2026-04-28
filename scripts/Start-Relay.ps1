<#
.SYNOPSIS
  Start the kabu-relay as a detached background process on this machine.

.DESCRIPTION
  - Loads secrets from ../.env (KABU_API_PASSWORD; KABU_ORDER_PASSWORD ignored).
  - Loads bearer token from ../data/.bearer (creates a fresh one if missing).
  - Launches `python -m app.main` via Start-Process with WindowStyle Hidden so
    the process survives the launcher's shell session.
  - Records the child PID in ../data/relay.pid.
  - Redirects stdout/stderr to ../logs/relay.stdout.log / relay.stderr.log
    in addition to the rotating ../logs/relay.log written by the app itself.

.PARAMETER Foreground
  Run in the foreground (blocks the shell). Useful for ad-hoc debugging.
#>

param(
    [switch]$Foreground
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# --- 1. Load .env (KEY=VALUE per line, # comments allowed) -----------------
$envFile = Join-Path $root '.env'
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^\s*#') { return }
        if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') {
            $name = $matches[1]
            $value = $matches[2].Trim()
            # Strip surrounding single or double quotes if present.
            if ($value.Length -ge 2 -and (
                ($value.StartsWith('"') -and $value.EndsWith('"')) -or
                ($value.StartsWith("'") -and $value.EndsWith("'"))
            )) {
                $value = $value.Substring(1, $value.Length - 2)
            }
            Set-Item -Path "Env:$name" -Value $value
        }
    }
} else {
    Write-Warning "$envFile not found. KABU_API_PASSWORD must be set externally."
}

if (-not $env:KABU_API_PASSWORD) {
    Write-Error "KABU_API_PASSWORD is not set (check .env or shell env)"
    exit 1
}

# --- 2. Bearer token -------------------------------------------------------
$dataDir = Join-Path $root 'data'
if (-not (Test-Path $dataDir)) { New-Item -ItemType Directory -Path $dataDir | Out-Null }
$bearerFile = Join-Path $dataDir '.bearer'
if (-not (Test-Path $bearerFile)) {
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $bytes = New-Object byte[] 32
    $rng.GetBytes($bytes)
    $token = [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+','-').Replace('/','_')
    Set-Content -Path $bearerFile -Value $token -NoNewline -Encoding ASCII
    Write-Output "generated new bearer at $bearerFile"
}
$env:KABU_RELAY_BEARER_TOKEN = (Get-Content $bearerFile -Raw).Trim()
$env:KABU_RELAY_CONFIG = Join-Path $root 'config\relay_config.json'

# --- 3. Already running? --------------------------------------------------
$port = 18091
$existing = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($existing) {
    Write-Output "relay is already listening on $port (PID $($existing.OwningProcess)). Stop-Relay.ps1 first."
    exit 0
}

# --- 4. Launch ------------------------------------------------------------
$logsDir = Join-Path $root 'logs'
if (-not (Test-Path $logsDir)) { New-Item -ItemType Directory -Path $logsDir | Out-Null }
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    Write-Error "$python not found. Create the venv first: uv venv --python 3.11 .venv ; uv pip install -r requirements.txt"
    exit 1
}

if ($Foreground) {
    & $python -m app.main
    exit $LASTEXITCODE
}

$stdout = Join-Path $logsDir 'relay.stdout.log'
$stderr = Join-Path $logsDir 'relay.stderr.log'
$proc = Start-Process `
    -FilePath $python `
    -ArgumentList '-m','app.main' `
    -WorkingDirectory $root `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdout `
    -RedirectStandardError  $stderr `
    -PassThru

Set-Content -Path (Join-Path $dataDir 'relay.pid') -Value $proc.Id -NoNewline -Encoding ASCII
Write-Output "started detached PID=$($proc.Id) on port $port"
Write-Output "  stdout -> $stdout"
Write-Output "  stderr -> $stderr"
Write-Output "  app log -> logs\relay.log (rotating)"
Write-Output ""
Write-Output "Wait ~3s, then run:  scripts\Status-Relay.ps1"
