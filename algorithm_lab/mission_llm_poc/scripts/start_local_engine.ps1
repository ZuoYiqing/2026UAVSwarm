param(
    [switch]$CheckOnly,
    [ValidateSet('qwen3.5-4b', 'qwen3.5-0.8b')][string]$ModelProfile = 'qwen3.5-4b',
    [ValidateRange(512, 8192)][int]$ContextTokens = 4096,
    [ValidateRange(1024, 65535)][int]$Port = 18080
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$moduleRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if (-not $moduleRoot.StartsWith('D:\', [StringComparison]::OrdinalIgnoreCase)) { throw 'D: deployment only.' }
$artifactRoot = Join-Path $moduleRoot 'artifacts'
$engineRoot = Join-Path $artifactRoot 'runtime/llama-b10964-cuda12.4'
$manifest = Get-Content (Join-Path $moduleRoot 'docs/DOWNLOAD_PROPOSAL_20260920.json') -Raw | ConvertFrom-Json
$modelAlias = 'qwen3.5-4b-q4-lab'
$minimumHostKiB = 5 * 1024 * 1024
$minimumGpuMiB = 4608
$modelLicense = 'qwen3.5-4b-LICENSE.txt'
$quantizerNotice = 'quantizer-model-card.md'
if ($ModelProfile -eq 'qwen3.5-0.8b') {
    $smallManifest = Get-Content (Join-Path $moduleRoot 'docs/QWEN_0_8B_DOWNLOAD_20261005.json') -Raw | ConvertFrom-Json
    $manifest.artifacts = @($manifest.artifacts | Where-Object role -ne 'text_model') + @($smallManifest.artifacts)
    $modelAlias = 'qwen3.5-0.8b-q4-lab'
    # Experimental admission budgets, not measured peaks or a 4B guard relaxation.
    $minimumHostKiB = 3 * 1024 * 1024
    $minimumGpuMiB = 2048
    $modelLicense = 'qwen3.5-0.8b-LICENSE.txt'
    $quantizerNotice = 'qwen3.5-0.8b-quantizer-model-card.md'
}
$verifiedPaths = @{}
foreach ($artifact in $manifest.artifacts) {
    $path = [IO.Path]::GetFullPath((Join-Path $moduleRoot $artifact.proposed_local_relative_path))
    if (-not $path.StartsWith($artifactRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Artifact path escaped D: experiment.' }
    if (-not (Test-Path -LiteralPath $path)) { throw "Missing local artifact; no automatic download: $path" }
    if ((Get-Item -LiteralPath $path).Length -ne $artifact.size_bytes -or
        (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $artifact.sha256) {
        throw "Artifact failed verification: $($artifact.filename)"
    }
    $verifiedPaths[$artifact.role] = $path
}
foreach ($license in @($modelLicense, $quantizerNotice, 'llama-b10964-LICENSE.txt', 'cuda-12.4.1-eula.html')) {
    if (-not (Test-Path -LiteralPath (Join-Path $artifactRoot "licenses/$license"))) { throw "Missing license/provenance: $license" }
}
New-Item -ItemType Directory -Path $engineRoot -Force | Out-Null
foreach ($role in @('inference_engine_archive', 'cuda_runtime_archive')) {
    $archive = [IO.Compression.ZipFile]::OpenRead($verifiedPaths[$role])
    try {
        foreach ($entry in $archive.Entries) {
            $destination = [IO.Path]::GetFullPath((Join-Path $engineRoot $entry.FullName))
            if (-not $destination.StartsWith($engineRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
                throw 'Unsafe archive path; extraction refused.'
            }
        }
        foreach ($entry in $archive.Entries) {
            $destination = [IO.Path]::GetFullPath((Join-Path $engineRoot $entry.FullName))
            if ($entry.FullName.EndsWith('/')) {
                New-Item -ItemType Directory -Path $destination -Force | Out-Null
                continue
            }
            New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
            if (Test-Path -LiteralPath $destination) {
                $entryStream = $entry.Open()
                try { $expectedHash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($entryStream)) } finally { $entryStream.Dispose() }
                if ((Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash -ne $expectedHash) { throw 'Existing engine file differs; not overwriting.' }
            } else {
                [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $destination, $false)
            }
        }
    } finally { $archive.Dispose() }
}
foreach ($cacheDir in @('tmp', 'cache/cuda', 'cache/models', 'cache/hf', 'cache/xdg')) {
    New-Item -ItemType Directory -Path (Join-Path $artifactRoot $cacheDir) -Force | Out-Null
}
$env:TEMP = Join-Path $artifactRoot 'tmp'
$env:TMP = $env:TEMP
$env:CUDA_CACHE_PATH = Join-Path $artifactRoot 'cache/cuda'
$env:LLAMA_CACHE = Join-Path $artifactRoot 'cache/models'
$env:HF_HOME = Join-Path $artifactRoot 'cache/hf'
$env:XDG_CACHE_HOME = Join-Path $artifactRoot 'cache/xdg'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
if (@(Get-ChildItem Env: | Where-Object Name -Like 'LLAMA_ARG_*').Count) {
    throw 'Inherited engine options detected; inspect them before a reproducible run.'
}
$engine = Join-Path $engineRoot 'llama-server.exe'
& $engine --version
if ($LASTEXITCODE -ne 0) { throw 'Engine version check failed.' }
& $engine --list-devices
if ($LASTEXITCODE -ne 0) { throw 'Engine device check failed.' }
if ($CheckOnly) { return }
$freeMemoryKiB = (Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory
if ($freeMemoryKiB -lt $minimumHostKiB) { throw "Insufficient RAM for $ModelProfile admission budget ($minimumHostKiB KiB). Do not force loading." }
$gpuFreeMiB = [int]((& nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits | Select-Object -First 1).Trim())
if ($LASTEXITCODE -ne 0 -or $gpuFreeMiB -lt $minimumGpuMiB) { throw "Insufficient free GPU memory for $ModelProfile admission budget." }
$probe = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $Port)
try { $probe.Start() } finally { $probe.Stop() }
$runRoot = Join-Path $artifactRoot ('runs/' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ'))
New-Item -ItemType Directory -Path $runRoot | Out-Null
$arguments = @('-m', $verifiedPaths['text_model'], '--alias', $modelAlias,
    '--host', '127.0.0.1', '--port', "$Port", '--offline', '--no-webui', '--no-agent',
    '--no-ui-mcp-proxy', '--cors-origins', "http://127.0.0.1:$Port", '--no-cors-credentials',
    '--no-slots', '--ctx-size', "$ContextTokens", '--parallel', '1',
    '--threads', '4', '--threads-batch', '4', '--batch-size', '256', '--ubatch-size', '128',
    '--gpu-layers', 'all', '--fit', 'off', '--reasoning', 'off', '--no-context-shift')
$engineProcess = Start-Process -FilePath $engine -ArgumentList $arguments -WorkingDirectory $engineRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runRoot 'server.stdout.log') -RedirectStandardError (Join-Path $runRoot 'server.stderr.log')
$record = [ordered]@{pid=$engineProcess.Id; executable=$engine; model=$verifiedPaths['text_model']; model_profile=$ModelProfile; model_alias=$modelAlias; port=$Port; minimum_host_kib=$minimumHostKiB; minimum_gpu_mib=$minimumGpuMiB; arguments=$arguments; run_directory=$runRoot; started_utc=[DateTime]::UtcNow.ToString('o'); offline_flag=$true; network_isolation_verified=$false; execution_authorized=$false; startup_status='loading'; memory_samples_kib=@(); guard_scope='startup_only'}
$launchPath = Join-Path $runRoot 'launch.json'
$record | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $launchPath -Encoding utf8
try {
    $ready = $false
    for ($poll = 0; $poll -lt 60; $poll++) {
        if ($engineProcess.HasExited) { throw 'Model process exited during startup; inspect stderr.' }
        $freeMemoryKiB = (Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory
        $record.memory_samples_kib += $freeMemoryKiB
        if ($freeMemoryKiB -lt 1536 * 1024) { throw 'Host RAM below 1.5 GiB during startup; stopping this model only.' }
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 1
            if ($health.status -eq 'ok') { $ready = $true; break }
        } catch { }
        Start-Sleep -Milliseconds 500
    }
    if (-not $ready) { throw 'Model did not become healthy during the bounded startup check.' }
    $record.startup_status = 'ready'
} catch {
    if (-not $engineProcess.HasExited) { Stop-Process -Id $engineProcess.Id }
    $record.startup_status = 'stopped'
    $record['startup_error'] = $_.Exception.Message
    $record | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $launchPath -Encoding utf8
    throw
}
$record | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $launchPath -Encoding utf8
$record | ConvertTo-Json -Depth 5
