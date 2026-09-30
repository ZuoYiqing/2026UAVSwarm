# Offline tests: fake HTTP responses and tiny generated fixtures on D:, no model loading.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$moduleRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$fixtureRoot = Join-Path $moduleRoot ('artifacts/tests/download-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $fixtureRoot -Force | Out-Null
$global:LabDownloadTestData = [Text.Encoding]::UTF8.GetBytes('tiny-offline-fixture')
$global:LabDownloadTestRequests = 0
$global:LabDownloadTestMode = 'normal'
$global:LabDownloadTestLastRange = ''
function Invoke-WebRequest {
    param($Uri, $Headers, $OutFile, [switch]$PassThru, $ConnectionTimeoutSeconds, $OperationTimeoutSeconds, $MaximumRedirection)
    $global:LabDownloadTestRequests++
    $global:LabDownloadTestLastRange = $Headers.Range
    if ($Headers.Range -notmatch '^bytes=(\d+)-(\d+)$') { throw 'Invalid test range.' }
    $start = [int]$Matches[1]
    $end = [int]$Matches[2]
    [byte[]]$chunk = $global:LabDownloadTestData[$start..$end]
    if ($global:LabDownloadTestMode -eq 'bad-content') { $chunk[0] = 0 }
    [IO.File]::WriteAllBytes($OutFile, $chunk)
    $range = 'bytes {0}-{1}/{2}' -f $start, $end, $global:LabDownloadTestData.Length
    if ($global:LabDownloadTestMode -eq 'bad-range') { $range = 'bytes 0-0/1' }
    return @{StatusCode=206; Headers=@{'Content-Range'=$range}}
}
function New-TestManifest([string]$Name, [string]$RelativePath = '', [string]$Url = 'https://huggingface.co/reviewed/test', [string]$Hash = '') {
    if (-not $RelativePath) { $RelativePath = 'artifacts/tests/' + (Split-Path $fixtureRoot -Leaf) + "/$Name.bin" }
    if (-not $Hash) { $Hash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($global:LabDownloadTestData)).ToLowerInvariant() }
    $manifest = @{status='PROPOSED_NOT_DOWNLOADED'; proposed_free_disk_budget_bytes=0; artifacts=@(
        @{filename="$Name.bin"; proposed_local_relative_path=$RelativePath; size_bytes=$global:LabDownloadTestData.Length; sha256=$Hash; url=$Url})}
    $path = Join-Path $fixtureRoot "$Name.json"
    $manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $path -Encoding utf8
    return $path
}
function Assert-Lab([bool]$Condition, [string]$Message) { if (-not $Condition) { throw $Message } }
function Expect-Rejection([string]$Manifest, [string]$Expected) {
    $rejected = $false
    try { & (Join-Path $moduleRoot 'scripts/prepare_local_artifacts.ps1') -ManifestPath $Manifest | Out-Null }
    catch { if ($_.Exception.Message -notlike "*$Expected*") { throw }; $rejected = $true }
    Assert-Lab $rejected "Expected rejection: $Expected"
}
$valid = New-TestManifest 'valid'
& (Join-Path $moduleRoot 'scripts/prepare_local_artifacts.ps1') -ManifestPath $valid | Out-Null
Assert-Lab ((Get-Item (Join-Path $fixtureRoot 'valid.bin')).Length -eq $global:LabDownloadTestData.Length) 'Valid download missing.'
$count = $global:LabDownloadTestRequests
& (Join-Path $moduleRoot 'scripts/prepare_local_artifacts.ps1') -ManifestPath $valid | Out-Null
Assert-Lab ($global:LabDownloadTestRequests -eq $count) 'Verified artifact was downloaded again.'
[IO.File]::WriteAllBytes((Join-Path $fixtureRoot 'valid.bin'), [byte[]]@(0))
Expect-Rejection $valid 'Existing file does not match'
$resume = New-TestManifest 'resume'
[IO.File]::WriteAllBytes((Join-Path $fixtureRoot 'resume.bin.part'), [byte[]]$global:LabDownloadTestData[0..2])
& (Join-Path $moduleRoot 'scripts/prepare_local_artifacts.ps1') -ManifestPath $resume | Out-Null
Assert-Lab ($global:LabDownloadTestLastRange.StartsWith('bytes=3-')) 'Resume offset was not preserved.'
$global:LabDownloadTestMode = 'bad-range'
Expect-Rejection (New-TestManifest 'bad-range') 'Range download failed'
Assert-Lab (-not (Test-Path (Join-Path $fixtureRoot 'bad-range.bin'))) 'Bad range accepted.'
$global:LabDownloadTestMode = 'bad-content'
Expect-Rejection (New-TestManifest 'bad-content') 'Downloaded size/hash mismatch'
Assert-Lab (-not (Test-Path (Join-Path $fixtureRoot 'bad-content.bin'))) 'Bad content accepted.'
$global:LabDownloadTestMode = 'normal'
Expect-Rejection (New-TestManifest 'escape' '../outside-artifact-test.bin') 'target escapes'
Expect-Rejection (New-TestManifest 'host' '' 'https://example.invalid/weight') 'Unapproved source'
Expect-Rejection (New-TestManifest 'hash' '' 'https://huggingface.co/reviewed/test' 'invalid') 'Invalid artifact'
Write-Output 'DOWNLOAD_SCRIPT_TESTS_PASSED=9; NETWORK_REQUESTS=0; MODEL_LOADS=0'
Write-Output "Generated test fixtures retained: $fixtureRoot"
$global:LASTEXITCODE = 0
