param(
    [Parameter(Mandatory=$true)][string]$LaunchRecord,
    [string]$ContextFile = 'examples/three_uav_inspection.json',
    [switch]$KeepServer
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$moduleRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$artifactRoot = Join-Path $moduleRoot 'artifacts'
$launchPath = [IO.Path]::GetFullPath($LaunchRecord)
if (-not $launchPath.StartsWith((Join-Path $artifactRoot 'runs') + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Launch record must belong to this experiment.' }
$launch = Get-Content -LiteralPath $launchPath -Raw | ConvertFrom-Json
$expectedEngine = Join-Path $artifactRoot 'runtime/llama-b10964-cuda12.4/llama-server.exe'
$server = Get-Process -Id $launch.pid
if ($server.Path -ne $expectedEngine -or $launch.startup_status -ne 'ready') { throw 'Expected local model is not ready.' }
$contextPath = [IO.Path]::GetFullPath((Join-Path $moduleRoot $ContextFile))
if (-not $contextPath.StartsWith($moduleRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase) -or -not (Test-Path -LiteralPath $contextPath)) { throw 'Context must be an existing local experiment file.' }
$runRoot = Join-Path $artifactRoot ('runs/request-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ'))
New-Item -ItemType Directory -Path $runRoot | Out-Null
$env:TEMP = Join-Path $artifactRoot 'tmp'
$env:TMP = $env:TEMP
$env:PYTHONPYCACHEPREFIX = Join-Path $artifactRoot 'cache/python'
$env:PYTHONPATH = Join-Path $moduleRoot 'src'
$outputPath = Join-Path $runRoot 'proposal.json'
$python = Join-Path $moduleRoot '.venv/Scripts/python.exe'
# Current checkout paths contain no spaces; quote each argument for portable launches.
$argumentValues = @('-m','uavswarm_llm_lab','infer',$contextPath,'--base-url','http://127.0.0.1:18080/v1',
    '--model','qwen3.5-4b-q4-lab','--max-tokens','1024','--timeout-s','90','--output',$outputPath)
$quotedArguments = @($argumentValues | ForEach-Object { '"' + $_ + '"' })
$client = Start-Process -FilePath $python -ArgumentList $quotedArguments -WorkingDirectory $moduleRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runRoot 'client.stdout.log') -RedirectStandardError (Join-Path $runRoot 'client.stderr.log')
$samples = [Collections.Generic.List[object]]::new()
$watch = [Diagnostics.Stopwatch]::StartNew()
$stopReason = $null
try {
    while (-not $client.HasExited) {
        $freeKiB = (Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory
        $gpuLine = & nvidia-smi --query-gpu=memory.used,memory.free,temperature.gpu,utilization.gpu --format=csv,noheader,nounits
        if ($LASTEXITCODE -ne 0) { throw 'GPU monitoring unavailable; stopping this test.' }
        $gpu = (($gpuLine | Select-Object -First 1) -split ',') | ForEach-Object { [int]$_.Trim() }
        $samples.Add([ordered]@{elapsed_s=$watch.Elapsed.TotalSeconds; host_free_kib=$freeKiB; gpu_used_mib=$gpu[0]; gpu_free_mib=$gpu[1]; temperature_c=$gpu[2]; gpu_utilization_percent=$gpu[3]})
        if ($freeKiB -lt 1536*1024) { throw 'LOW_HOST_RAM' }
        if ($gpu[2] -ge 85) { throw 'EXPERIMENT_TEMPERATURE_LIMIT' }
        if ($watch.Elapsed.TotalSeconds -gt 120) { throw 'EXPERIMENT_TIMEOUT' }
        if ($server.HasExited) { throw 'MODEL_PROCESS_EXITED' }
        Start-Sleep -Milliseconds 500
    }
    $client.WaitForExit()
} catch {
    $stopReason = $_.Exception.Message
    if (-not $client.HasExited) { Stop-Process -Id $client.Id }
    if (-not $server.HasExited) { Stop-Process -Id $server.Id }
} finally {
    $serverStoppedAfterRequest = $false
    if (-not $KeepServer -and -not $server.HasExited) {
        Stop-Process -Id $server.Id
        $serverStoppedAfterRequest = $true
    }
    $report = [ordered]@{kind='single_request_resource_samples'; context=$ContextFile; launch_record=$launchPath; proposal_path=$outputPath; elapsed_s=$watch.Elapsed.TotalSeconds; stop_reason=$stopReason; sample_count=$samples.Count; server_stopped_after_request=$serverStoppedAfterRequest; samples=$samples; note='Whole-GPU point samples, not exclusive model memory or guaranteed transient peaks.'}
    $report | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $runRoot 'resources.json') -Encoding utf8
}
Write-Output "REQUEST_ARTIFACTS=$runRoot"
if ($stopReason) { throw "Experiment stopped: $stopReason" }
Get-Content -LiteralPath (Join-Path $runRoot 'client.stdout.log')
$clientExitCode = $client.ExitCode
if ($clientExitCode -ne 0) {
    Get-Content -LiteralPath (Join-Path $runRoot 'client.stderr.log')
    throw "Client returned $clientExitCode; original output retained."
}
