param([string]$ManifestPath = (Join-Path $PSScriptRoot '../docs/DOWNLOAD_PROPOSAL_20260920.json'))
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$moduleRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if (-not $moduleRoot.StartsWith('D:\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'This experiment is approved for D: only.'
}
$artifactRoot = Join-Path $moduleRoot 'artifacts'
$tempRoot = Join-Path $artifactRoot 'tmp'
New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
$env:TEMP = $tempRoot
$env:TMP = $tempRoot
$manifest = Get-Content -LiteralPath $ManifestPath -Raw -Encoding utf8 | ConvertFrom-Json
if ($manifest.status -ne 'PROPOSED_NOT_DOWNLOADED') { throw 'Expected a reviewed proposal manifest.' }
if ((Get-PSDrive -Name D).Free -lt $manifest.proposed_free_disk_budget_bytes) {
    throw 'Less than the proposed D: disk reserve is available.'
}
foreach ($artifact in $manifest.artifacts) {
    $target = [IO.Path]::GetFullPath((Join-Path $moduleRoot $artifact.proposed_local_relative_path))
    if (-not $target.StartsWith($artifactRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Artifact target escapes the local artifact directory.'
    }
    if ($artifact.sha256 -notmatch '^[a-f0-9]{64}$' -or $artifact.size_bytes -le 0) { throw 'Invalid artifact size or hash.' }
    $uri = [uri]$artifact.url
    if ($uri.Scheme -ne 'https' -or $uri.Host -notin @('huggingface.co', 'github.com')) { throw 'Unapproved source host.' }
    New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
    $partial = $target + '.part'
    $chunk = $partial + '.chunk'
    if (Test-Path -LiteralPath $target) {
        $hash = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()
        if ((Get-Item -LiteralPath $target).Length -ne $artifact.size_bytes -or $hash -ne $artifact.sha256) {
            throw "Existing file does not match the approved artifact: $target"
        }
        if (Test-Path -LiteralPath $chunk) { Remove-Item -LiteralPath $chunk }
        Write-Output "ALREADY_VERIFIED $($artifact.filename)"
        continue
    }
    if ((Test-Path -LiteralPath $partial) -and (Get-Item -LiteralPath $partial).Length -gt $artifact.size_bytes) {
        throw 'Partial file exceeds expected size; retained for inspection.'
    }
    Write-Output "DOWNLOAD_START $($artifact.filename) expected_bytes=$($artifact.size_bytes)"
    # Bounded range requests keep transfers resumable and memory use limited.
    $ProgressPreference = 'SilentlyContinue'
    [long]$offset = if (Test-Path -LiteralPath $partial) { (Get-Item -LiteralPath $partial).Length } else { 0 }
    while ($offset -lt $artifact.size_bytes) {
        [long]$end = [Math]::Min($offset + 64MB - 1, $artifact.size_bytes - 1)
        $expectedRange = "bytes ${offset}-${end}/$($artifact.size_bytes)"
        for ($attempt = 1; $attempt -le 3; $attempt++) {
            try {
                $response = Invoke-WebRequest -Uri $artifact.url -Headers @{Range="bytes=$offset-$end"} -OutFile $chunk -PassThru -ConnectionTimeoutSeconds 30 -OperationTimeoutSeconds 180 -MaximumRedirection 10
                if ($response.StatusCode -ne 206 -or [string]$response.Headers['Content-Range'] -ne $expectedRange -or
                    (Get-Item -LiteralPath $chunk).Length -ne ($end - $offset + 1)) {
                    throw 'Unexpected HTTP range response; not appending bytes.'
                }
                break
            } catch {
                if ($attempt -eq 3) { throw "Range download failed; partial file retained on D: $($_.Exception.Message)" }
                Write-Output "RANGE_RETRY $($artifact.filename) offset=$offset attempt=$attempt"
            }
        }
        $sourceStream = [IO.File]::OpenRead($chunk)
        $targetStream = [IO.File]::Open($partial, [IO.FileMode]::Append, [IO.FileAccess]::Write, [IO.FileShare]::Read)
        try { $sourceStream.CopyTo($targetStream) } finally { $sourceStream.Dispose(); $targetStream.Dispose() }
        Remove-Item -LiteralPath $chunk
        $offset = $end + 1
        Write-Output "DOWNLOAD_PROGRESS $($artifact.filename) bytes=$offset/$($artifact.size_bytes)"
    }
    $hash = (Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash.ToLowerInvariant()
    if ((Get-Item -LiteralPath $partial).Length -ne $artifact.size_bytes -or $hash -ne $artifact.sha256) {
        throw 'Downloaded size/hash mismatch; artifact not accepted.'
    }
    Move-Item -LiteralPath $partial -Destination $target
    Write-Output "VERIFIED $($artifact.filename) sha256=$hash"
}
Write-Output 'ALL_APPROVED_ARTIFACTS_VERIFIED; NO SOFTWARE EXECUTED'
