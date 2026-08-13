param(
    [switch]$FullPytest,
    [string]$PytestBaseTemp = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$failedSteps = [System.Collections.Generic.List[string]]::new()
$auditPath = Join-Path $repoRoot "audit\runtime.audit.jsonl"

function Get-AuditHash {
    if (-not (Test-Path -LiteralPath $auditPath)) {
        return "<missing>"
    }
    return (Get-FileHash -LiteralPath $auditPath -Algorithm SHA256).Hash
}

function Invoke-AcceptanceStep {
    param(
        [string]$Name,
        [string]$Executable,
        [string[]]$Arguments,
        [string]$WorkingDirectory
    )

    Write-Host "`n== $Name =="
    Push-Location $WorkingDirectory
    try {
        & $Executable @Arguments
        if ($LASTEXITCODE -ne 0) {
            $failedSteps.Add("$Name (exit $LASTEXITCODE)")
        }
    }
    finally {
        Pop-Location
    }
}

Set-Location $repoRoot
git status --short --branch
$auditBefore = Get-AuditHash

$pytestArgs = @("-m", "pytest", "-ra")
if (-not $FullPytest) {
    $pytestArgs += @(
        "tests/integration/test_four_module_e2e_acceptance.py",
        "tests/integration/test_px4_multi_vehicle_runtime.py",
        "tests/unit/test_audit_isolation.py"
    )
}
if ($PytestBaseTemp) {
    $pytestArgs += @("--basetemp", $PytestBaseTemp)
}

$pythonLabel = if ($FullPytest) { "Full Python pytest" } else { "Four-module Python acceptance" }
Invoke-AcceptanceStep $pythonLabel "python" $pytestArgs $repoRoot
Invoke-AcceptanceStep "Main console model and action routing" "npm" @("test") (Join-Path $repoRoot "frontend\swarm-console")
Invoke-AcceptanceStep "Main console syntax check" "npm" @("run", "check") (Join-Path $repoRoot "frontend\swarm-console")
Invoke-AcceptanceStep "Cesium vehicle snapshot" "npm" @("test") (Join-Path $repoRoot "frontend\swarm-console\simulation-3d")

$auditAfter = Get-AuditHash
if ($auditAfter -ne $auditBefore) {
    $failedSteps.Add("Git-managed audit/runtime.audit.jsonl changed during acceptance")
}

if ($failedSteps.Count -gt 0) {
    Write-Host "`nAcceptance failed:"
    $failedSteps | ForEach-Object { Write-Host "- $_" }
    exit 1
}

Write-Host "`nAcceptance passed; the managed audit file hash is unchanged."
exit 0
