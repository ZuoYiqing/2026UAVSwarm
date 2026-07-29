[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$Port = 5179
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $projectRoot ".vite-dev.pid"
$stdoutFile = Join-Path $projectRoot ".vite-dev.stdout.log"
$stderrFile = Join-Path $projectRoot ".vite-dev.stderr.log"

if (Test-Path -LiteralPath $pidFile) {
    $existingPidText = (Get-Content -LiteralPath $pidFile -Raw).Trim()
    $existingPid = 0
    if ([int]::TryParse($existingPidText, [ref]$existingPid)) {
        $existingProcess = Get-Process -Id $existingPid -ErrorAction SilentlyContinue
        if ($null -ne $existingProcess) {
            Write-Host "Development server is already running (PID $existingPid)."
            Write-Host "URL: http://127.0.0.1:$Port/"
            exit 0
        }
    }
    Remove-Item -LiteralPath $pidFile -Force
}

$npmCommand = (Get-Command npm.cmd -ErrorAction Stop).Source

# Some Windows environments contain both "Path" and "PATH". Windows
# PowerShell's Start-Process rejects that duplicate key set.
$processPath = $env:Path
[Environment]::SetEnvironmentVariable("PATH", $null, "Process")
[Environment]::SetEnvironmentVariable("Path", $processPath, "Process")

$process = Start-Process `
    -FilePath $npmCommand `
    -ArgumentList @("run", "dev", "--", "--port", "$Port") `
    -WorkingDirectory $projectRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdoutFile `
    -RedirectStandardError $stderrFile `
    -PassThru

Set-Content -LiteralPath $pidFile -Value $process.Id -Encoding ascii
Start-Sleep -Seconds 2
$process.Refresh()

if ($process.HasExited) {
    Write-Error "Development server failed to start. Check $stderrFile"
}

Write-Host "Development server started (PID $($process.Id))."
Write-Host "URL: http://127.0.0.1:$Port/"
Write-Host "Stop: powershell -ExecutionPolicy Bypass -File .\scripts\stop-dev.ps1"
