$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$labRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$repoRoot = [IO.Path]::GetFullPath((Join-Path $labRoot '../..'))
$artifactRoot = Join-Path $labRoot 'artifacts'
$source = Join-Path $PSScriptRoot 'evaluate_anchoring_a_v04_preview.py'
$base = '46de1b79940d13c9aeb991c48897e93f7222ac9a'
if (-not $labRoot.StartsWith('D:\', [StringComparison]::OrdinalIgnoreCase)) { throw 'D: experiment only.' }
if ((git -C $repoRoot rev-parse HEAD) -ne $base -or $LASTEXITCODE -ne 0) {
    throw "Reproduce this A-v0.4 comparison at pinned baseline $base."
}
$minHostKiB = 5 * 1024 * 1024
$minGpuMiB = 4608
$stopHostKiB = 1536 * 1024
$maxTempC = 85
$maxEvalSec = 240
$port = 18116

function Measure-LabResources {
    $freeKiB = (Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory
    $gpu = & nvidia-smi --query-gpu=memory.used,memory.free,temperature.gpu --format=csv,noheader,nounits
    if ($LASTEXITCODE -ne 0) { throw 'GPU sampler failed.' }
    $numbers = (($gpu | Select-Object -First 1) -split ',') | ForEach-Object { [int]$_.Trim() }
    if ($numbers.Count -ne 3) { throw 'GPU sample malformed.' }
    [ordered]@{
        utc = [DateTime]::UtcNow.ToString('o')
        host_free_kib = $freeKiB
        gpu_used_mib = $numbers[0]
        gpu_free_mib = $numbers[1]
        temperature_c = $numbers[2]
    }
}

$runRoot = Join-Path $artifactRoot ('a-v04-qwen4b-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ'))
New-Item -ItemType Directory -Path $runRoot | Out-Null
Write-Output "EXPERIMENT_ARTIFACTS=$runRoot"
$resourceReport = [ordered]@{
    model = 'qwen3.5-4b-q4-lab'
    context_tokens = 2048
    port = $port
    preflight = $null
    minimum_host_kib = $minHostKiB
    minimum_gpu_mib = $minGpuMiB
    stop_host_kib = $stopHostKiB
    stop_temperature_c = $maxTempC
    evaluator_sha256 = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
    launch_record = $null
    stop_reason = $null
    evaluation_exit_code = $null
    model_exited = $null
    execution_authorized = $false
    samples = @()
}
$samples = [Collections.Generic.List[object]]::new()
$server = $null
$client = $null
try {
    $resourceReport.preflight = Measure-LabResources
    if ($resourceReport.preflight.host_free_kib -lt $minHostKiB -or
        $resourceReport.preflight.gpu_free_mib -lt $minGpuMiB) { throw 'ADMISSION_RESOURCES_INSUFFICIENT' }
    $env:PYTHONPATH = "$(Join-Path $repoRoot 'src');$(Join-Path $labRoot 'src');$repoRoot"
    $env:PYTHONIOENCODING = 'utf-8'
    $env:UAV_RUNTIME_VEHICLE_CONFIG = Join-Path $repoRoot 'config/vehicles.sitl.json'
    $env:UAV_RUNTIME_AUDIT_PATH = Join-Path $runRoot 'isolated.audit.jsonl'
    $launcherOutput = & (Join-Path $PSScriptRoot 'start_local_engine.ps1') -ModelProfile qwen3.5-4b -ContextTokens 2048 -Port $port
    $launch = $launcherOutput[-1] | ConvertFrom-Json
    $expectedEngine = Join-Path $artifactRoot 'runtime/llama-b10964-cuda12.4/llama-server.exe'
    $spawned = Get-Process -Id $launch.pid
    if ($spawned.Path -ne $expectedEngine) { throw 'Unexpected inference engine process; refusing to take ownership.' }
    $server = $spawned
    $resourceReport.launch_record = Join-Path $launch.run_directory 'launch.json'
    if ($launch.startup_status -ne 'ready' -or $launch.offline_flag -ne $true -or
        $launch.port -ne $port -or $launch.model_alias -ne $resourceReport.model) {
        throw 'Unexpected launch record.'
    }
    if ($launch.minimum_host_kib -ne $minHostKiB -or $launch.minimum_gpu_mib -ne $minGpuMiB) {
        throw 'Launcher admission constants changed.'
    }
    Write-Output "MODEL_READY=$($server.Id)"
    $python = (Get-Command python -CommandType Application).Source
    $argsList = @('-B', $source, '--output', (Join-Path $runRoot 'results'),
        '--model-url', "http://127.0.0.1:$port/v1", '--model-id', $launch.model_alias,
        '--launch-record', $resourceReport.launch_record)
    $quoted = @($argsList | ForEach-Object { '"' + $_ + '"' })
    $client = Start-Process -FilePath $python -ArgumentList $quoted -WorkingDirectory $repoRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runRoot 'evaluator.stdout.log') -RedirectStandardError (Join-Path $runRoot 'evaluator.stderr.log')
    $watch = [Diagnostics.Stopwatch]::StartNew()
    do {
        $sample = Measure-LabResources
        $sample['elapsed_s'] = $watch.Elapsed.TotalSeconds
        $samples.Add($sample)
        if ($sample.host_free_kib -lt $stopHostKiB) { throw 'LOW_HOST_RAM' }
        if ($sample.temperature_c -ge $maxTempC) { throw 'EXPERIMENT_TEMPERATURE_LIMIT' }
        if ($watch.Elapsed.TotalSeconds -gt $maxEvalSec) { throw 'EXPERIMENT_TIMEOUT' }
        if ($server.HasExited) { throw 'MODEL_PROCESS_EXITED' }
        if (-not $client.HasExited) { Start-Sleep -Milliseconds 500 }
    } while (-not $client.HasExited)
    $client.WaitForExit()
    $resourceReport.evaluation_exit_code = $client.ExitCode
    if ($client.ExitCode -ne 0) { throw "Evaluator exited with code $($client.ExitCode)." }
} catch {
    $resourceReport.stop_reason = $_.Exception.Message
    throw
} finally {
    if ($client -and -not $client.HasExited) { $client.Kill(); [void]$client.WaitForExit(5000) }
    if ($server -and -not $server.HasExited) { $server.Kill(); [void]$server.WaitForExit(5000) }
    if ($server) { $resourceReport.model_exited = $server.HasExited }
    $resourceReport.samples = @($samples.ToArray())
    $resourceReport | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $runRoot 'resources.json') -Encoding utf8
}
Get-Content -LiteralPath (Join-Path $runRoot 'evaluator.stdout.log')
