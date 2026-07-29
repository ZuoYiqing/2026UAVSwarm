[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$projectRoot = Split-Path -Parent $PSScriptRoot
$stageRoot = [System.IO.Path]::GetFullPath((Join-Path $projectRoot ".offline-stage"))
$zipPath = [System.IO.Path]::GetFullPath(
    (Join-Path $projectRoot "uavswarm-simulation-3d-offline.zip")
)
$hashPath = "$zipPath.sha256"
$distRoot = Join-Path $projectRoot "dist"
$deploymentRoot = Join-Path $projectRoot "deployment"
$guidePath = Join-Path $projectRoot "docs\OFFLINE_DEPLOYMENT_ZH-CN.md"
$contractGuidePath = Join-Path $projectRoot "docs\VEHICLE_FEED_CONTRACT_ZH-CN.md"
$handoffGuidePath = Join-Path $projectRoot "docs\CROSS_WORKSTREAM_PROMPTS_ZH-CN.md"
$cesiumLicense = Join-Path $projectRoot "node_modules\cesium\LICENSE.md"

Push-Location $projectRoot
try {
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) {
        throw "npm run build failed with exit code $LASTEXITCODE."
    }
} finally {
    Pop-Location
}

$requiredPaths = @(
    (Join-Path $distRoot "index.html"),
    (Join-Path $distRoot "cesium-static"),
    $guidePath,
    $contractGuidePath,
    $handoffGuidePath,
    $cesiumLicense
)
foreach ($requiredPath in $requiredPaths) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "Required path is missing: $requiredPath"
    }
}

$expectedStageRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $projectRoot ".offline-stage")
)
if ($stageRoot -ne $expectedStageRoot) {
    throw "Unexpected staging path: $stageRoot"
}

if (Test-Path -LiteralPath $stageRoot) {
    Remove-Item -LiteralPath $stageRoot -Recurse -Force
}
New-Item -ItemType Directory -Path (Join-Path $stageRoot "site") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $stageRoot "docs") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $stageRoot "licenses") -Force | Out-Null

Copy-Item -Path (Join-Path $distRoot "*") -Destination (Join-Path $stageRoot "site") -Recurse -Force
Copy-Item -LiteralPath (Join-Path $deploymentRoot "start-windows.ps1") -Destination $stageRoot
Copy-Item -LiteralPath (Join-Path $deploymentRoot "start-linux.sh") -Destination $stageRoot
Copy-Item -LiteralPath (Join-Path $deploymentRoot "nginx.conf.example") -Destination $stageRoot
Copy-Item -LiteralPath $guidePath -Destination (Join-Path $stageRoot "README_OFFLINE_ZH-CN.md")
Copy-Item -LiteralPath $contractGuidePath -Destination (Join-Path $stageRoot "docs")
Copy-Item -LiteralPath $handoffGuidePath -Destination (Join-Path $stageRoot "docs")
Copy-Item -LiteralPath $cesiumLicense -Destination (Join-Path $stageRoot "licenses\CESIUMJS_LICENSE.md")

$packageInfo = @(
    "UAVSwarm Simulation 3D offline package",
    "Created: $((Get-Date).ToString('yyyy-MM-dd HH:mm:ss K'))",
    "CesiumJS: 1.143.0",
    "Entry point: site/index.html",
    "Vehicle contract: docs/VEHICLE_FEED_CONTRACT_ZH-CN.md"
)
Set-Content -LiteralPath (Join-Path $stageRoot "PACKAGE_INFO.txt") -Value $packageInfo -Encoding utf8

if (Test-Path -LiteralPath $zipPath) {
    Remove-Item -LiteralPath $zipPath -Force
}
$zipStream = [System.IO.File]::Open(
    $zipPath,
    [System.IO.FileMode]::CreateNew,
    [System.IO.FileAccess]::ReadWrite,
    [System.IO.FileShare]::None
)
$zipArchive = [System.IO.Compression.ZipArchive]::new(
    $zipStream,
    [System.IO.Compression.ZipArchiveMode]::Create,
    $false
)
try {
    $stageFiles = Get-ChildItem -LiteralPath $stageRoot -Recurse -File
    foreach ($stageFile in $stageFiles) {
        $relativePath = $stageFile.FullName.Substring($stageRoot.Length)
        $relativePath = $relativePath.TrimStart([System.IO.Path]::DirectorySeparatorChar)
        $entryName = $relativePath.Replace(
            [System.IO.Path]::DirectorySeparatorChar,
            [System.IO.Path]::AltDirectorySeparatorChar
        )
        $entry = $zipArchive.CreateEntry(
            $entryName,
            [System.IO.Compression.CompressionLevel]::Optimal
        )
        $inputStream = [System.IO.File]::OpenRead($stageFile.FullName)
        $entryStream = $entry.Open()
        try {
            $inputStream.CopyTo($entryStream)
        } finally {
            $entryStream.Dispose()
            $inputStream.Dispose()
        }
    }
} finally {
    $zipArchive.Dispose()
    $zipStream.Dispose()
}
Remove-Item -LiteralPath $stageRoot -Recurse -Force

$zipHash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
$hashLine = "$zipHash *$(Split-Path -Leaf $zipPath)"
Set-Content -LiteralPath $hashPath -Value $hashLine -Encoding ascii

Write-Host "Offline package created:"
Write-Host $zipPath
Write-Host "SHA-256:"
Write-Host $zipHash
