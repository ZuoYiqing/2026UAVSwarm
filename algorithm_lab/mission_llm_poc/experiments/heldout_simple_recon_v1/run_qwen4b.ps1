param(
    [Parameter(Mandatory = $true)][string]$Launcher
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../../..'))
$lab = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
if (-not $repo.StartsWith('D:\', [StringComparison]::OrdinalIgnoreCase)) { throw 'D: experiment only.' }
$launcherPath = (Resolve-Path -LiteralPath $Launcher).Path
if (-not $launcherPath.StartsWith('D:\', [StringComparison]::OrdinalIgnoreCase) -or
    (Split-Path -Leaf $launcherPath) -ne 'start_local_engine.ps1') { throw 'Use the verified D: lab launcher.' }
$engineLab = Split-Path -Parent (Split-Path -Parent $launcherPath)
$enginePath = Join-Path $engineLab 'artifacts/runtime/llama-b10964-cuda12.4/llama-server.exe'
$freeze = '4596632544005ae7a7c2de993bd6b99e9af9c7cf'
$port = 18116
$minHostKiB = 5 * 1024 * 1024
$minGpuMiB = 4608

function Measure-LabResources {
    $ram = (Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory
    $gpu = & nvidia-smi --query-gpu=memory.used,memory.free,temperature.gpu --format=csv,noheader,nounits
    if ($LASTEXITCODE -ne 0) { throw 'GPU sampler failed.' }
    $numbers = (($gpu | Select-Object -First 1) -split ',') | ForEach-Object { [int]$_.Trim() }
    if ($numbers.Count -ne 3) { throw 'GPU sample malformed.' }
    [ordered]@{
        utc = [DateTime]::UtcNow.ToString('o')
        host_free_kib = $ram
        gpu_used_mib = $numbers[0]
        gpu_free_mib = $numbers[1]
        temperature_c = $numbers[2]
    }
}

$run = Join-Path $lab ('artifacts/heldout-simple-recon-qwen4b-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ'))
New-Item -ItemType Directory -Path $run | Out-Null
Write-Output "EXPERIMENT_ARTIFACTS=$run"
$samples = [Collections.Generic.List[object]]::new()
$resources = [ordered]@{
    model = 'qwen3.5-4b-q4-lab'
    minimum_host_kib = $minHostKiB
    minimum_gpu_mib = $minGpuMiB
    preflight = $null
    launch_record = $null
    evaluation_exit_code = $null
    stop_reason = $null
    model_exited = $null
    samples = @()
}
$server = $null
$client = $null
try {
    $resources.preflight = Measure-LabResources
    if ($resources.preflight.host_free_kib -lt $minHostKiB -or
        $resources.preflight.gpu_free_mib -lt $minGpuMiB) { throw 'ADMISSION_RESOURCES_INSUFFICIENT' }
    $launchOutput = & $launcherPath -ModelProfile qwen3.5-4b -ContextTokens 2048 -Port $port
    $launch = $launchOutput[-1] | ConvertFrom-Json
    $spawned = Get-Process -Id $launch.pid
    if ($spawned.Path -ne $enginePath) { throw 'Unexpected inference process; refusing ownership.' }
    $server = $spawned
    $resources.launch_record = Join-Path $launch.run_directory 'launch.json'
    if ($launch.port -ne $port -or $launch.minimum_host_kib -ne $minHostKiB -or
        $launch.minimum_gpu_mib -ne $minGpuMiB) { throw 'Unexpected launch settings.' }
    Write-Output "MODEL_READY=$($server.Id)"
    $env:PYTHONPATH = "$(Join-Path $repo 'src');$(Join-Path $lab 'src');$repo"
    $env:PYTHONIOENCODING = 'utf-8'
    $env:UAV_RUNTIME_VEHICLE_CONFIG = Join-Path $repo 'config/vehicles.sitl.json'
    $env:UAV_RUNTIME_AUDIT_PATH = Join-Path $run 'isolated.audit.jsonl'
    $python = (Get-Command python -CommandType Application).Source
    $argList = @('-B', (Join-Path $PSScriptRoot 'evaluate_qwen4b.py'), '--freeze-commit', $freeze,
        '--launch-record', $resources.launch_record, '--output', (Join-Path $run 'results'))
    $quoted = @($argList | ForEach-Object { '"' + $_ + '"' })
    $client = Start-Process -FilePath $python -ArgumentList $quoted -WorkingDirectory $repo -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $run 'eval.stdout.log') -RedirectStandardError (Join-Path $run 'eval.stderr.log')
    $watch = [Diagnostics.Stopwatch]::StartNew()
    do {
        $sample = Measure-LabResources
        $sample['elapsed_s'] = $watch.Elapsed.TotalSeconds
        $samples.Add($sample)
        if ($sample.host_free_kib -lt 1536 * 1024) { throw 'LOW_HOST_RAM' }
        if ($sample.temperature_c -ge 85) { throw 'EXPERIMENT_TEMPERATURE_LIMIT' }
        if ($watch.Elapsed.TotalSeconds -gt 540) { throw 'EXPERIMENT_TIMEOUT' }
        if ($server.HasExited) { throw 'MODEL_PROCESS_EXITED' }
        if (-not $client.HasExited) { Start-Sleep -Milliseconds 500 }
    } while (-not $client.HasExited)
    $client.WaitForExit()
    $resources.evaluation_exit_code = $client.ExitCode
    if ($client.ExitCode -ne 0) { throw "Evaluator failed: $($client.ExitCode)." }
} catch {
    $resources.stop_reason = $_.Exception.Message
    throw
} finally {
    if ($client -and -not $client.HasExited) { $client.Kill(); [void]$client.WaitForExit(5000) }
    if ($server -and -not $server.HasExited) { $server.Kill(); [void]$server.WaitForExit(5000) }
    if ($server) { $resources.model_exited = $server.HasExited }
    $resources.samples = @($samples.ToArray())
    $resources | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $run 'resources.json') -Encoding utf8
}
Get-Content -LiteralPath (Join-Path $run 'eval.stdout.log') -Tail 12
