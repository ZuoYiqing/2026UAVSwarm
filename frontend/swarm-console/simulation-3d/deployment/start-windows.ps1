[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$Port = 5179,
    [string]$Bind = "127.0.0.1"
)

$ErrorActionPreference = "Stop"
$siteRoot = Join-Path $PSScriptRoot "site"
if (-not (Test-Path -LiteralPath (Join-Path $siteRoot "index.html"))) {
    throw "site\index.html was not found. Extract the complete offline package first."
}

$pyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
if ($null -ne $pyLauncher) {
    Write-Host "Serving $siteRoot"
    Write-Host "URL: http://$Bind`:$Port/"
    Write-Host "Press Ctrl+C to stop."
    & $pyLauncher.Source -3 -m http.server $Port --bind $Bind --directory $siteRoot
    exit $LASTEXITCODE
}

$pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
if ($null -ne $pythonCommand) {
    Write-Host "Serving $siteRoot"
    Write-Host "URL: http://$Bind`:$Port/"
    Write-Host "Press Ctrl+C to stop."
    & $pythonCommand.Source -m http.server $Port --bind $Bind --directory $siteRoot
    exit $LASTEXITCODE
}

throw "Python 3 was not found. Use IIS/Nginx or install Python before moving into the offline network."

