[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $projectRoot ".vite-dev.pid"

if (-not (Test-Path -LiteralPath $pidFile)) {
    Write-Host "No development-server PID file was found."
    exit 0
}

$pidText = (Get-Content -LiteralPath $pidFile -Raw).Trim()
$serverPid = 0
if (-not [int]::TryParse($pidText, [ref]$serverPid)) {
    throw "Invalid PID file: $pidFile"
}

$process = Get-Process -Id $serverPid -ErrorAction SilentlyContinue
if ($null -eq $process) {
    Remove-Item -LiteralPath $pidFile -Force
    Write-Host "The recorded process is no longer running. Removed the stale PID file."
    exit 0
}

if ($process.ProcessName -notin @("cmd", "node", "npm")) {
    throw "Refusing to stop unexpected process '$($process.ProcessName)' with PID $serverPid."
}

& taskkill.exe /PID $serverPid /T /F | Out-Host
if ($LASTEXITCODE -ne 0) {
    throw "taskkill failed with exit code $LASTEXITCODE."
}

Remove-Item -LiteralPath $pidFile -Force
Write-Host "Development server stopped."

