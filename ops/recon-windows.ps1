# recon-windows.ps1 -- reconnaissance for a Windows target machine.
#
# WHY THIS EXISTS
#   The offline environment has both Ubuntu and Windows machines. The bash
#   recon script cannot run on Windows. This is the Windows counterpart, written
#   in PowerShell and using only what ships with Windows (no installs, no network).
#
# WHY THE LABELS ARE ASCII (English)
#   PowerShell 5.1 on zh-CN Windows often decodes a .ps1 as GBK. Chinese literals
#   in a UTF-8-saved .ps1 can come out as mojibake, and can even break
#   string formatting. Section labels are ASCII on purpose; a Chinese key is in
#   the accompanying chat message. Values (hostname, GPU names) may still contain
#   Chinese -- that is data, not source, so it passes through fine.
#
# HOW TO RUN
#   Right-click "Run with PowerShell", or in cmd:
#       powershell -NoProfile -ExecutionPolicy Bypass -File recon-windows.ps1
#   To also save a copy:
#       powershell -NoProfile -ExecutionPolicy Bypass -File recon-windows.ps1 *> $env:USERPROFILE\Desktop\recon-win.txt
#
# READ-ONLY. Changes nothing, installs nothing, does not touch the network.

$ErrorActionPreference = 'Continue'

function Sec([string]$t) { Write-Host ""; Write-Host ("=========== " + $t + " ===========") }
function Line([string]$k, [string]$v) { Write-Host ("  " + $k.PadRight(22) + ": " + $v) }

# ---------------------------------------------------------------------------
# TOP 5 -- printed FIRST, on purpose.
# The offline environment has no network, so the result may have to leave by
# USB stick, by reading the screen, or by photographing it. These five lines are
# the ones that actually gate the migration, so they go first and stay short
# enough to fit in one photo.
# ---------------------------------------------------------------------------
Sec "TOP 5  (photograph just this block if you cannot copy files out)"
$topPython = "(none found)"
$c0 = Get-Command python -ErrorAction SilentlyContinue
if ($c0) {
    try { $topPython = ((& $c0.Source --version 2>&1 | Out-String).Trim()) + "   " + $c0.Source } catch { $topPython = $c0.Source }
}
Line "T1 python" $topPython
Line "T1 note"   "project needs >= 3.10"

$gpuNames = @()
try {
    $gpuNames = @(Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue | ForEach-Object { $_.Name })
} catch { }
Line "T2 GPU" ($(if ($gpuNames.Count) { $gpuNames -join ' | ' } else { '(unknown)' }))
Line "T2 note" "Intel-only means the 3D view renders slowly"

$cFree = ""
try {
    $l = Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" -ErrorAction SilentlyContinue |
        ForEach-Object { $_.DeviceID + " free " + [math]::Round($_.FreeSpace / 1GB, 1) + "GB" }
    $cFree = ($l -join "   ")
} catch { }
Line "T3 disk" $(if ($cFree) { $cFree } else { '(unknown)' })

$n = Get-Command node -ErrorAction SilentlyContinue
Line "T4 node" $(if ($n) { ((& $n.Source --version 2>&1 | Out-String).Trim()) + "   " + $n.Source } else { "NOT FOUND (the 3D console needs it)" })

$hasWsl = [bool](Get-Command wsl -ErrorAction SilentlyContinue)
Line "T5 WSL" $(if ($hasWsl) { "wsl.exe present -> bash MAY be available; see section 6" } else { "NOT FOUND -> use only this script" })

Sec "0. HOST"
Line "hostname"   $env:COMPUTERNAME
Line "user"       $env:USERNAME
Line "time"       (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
Line "isAdmin"    ([bool](New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator))

Sec "1. WINDOWS"
try {
    $os = Get-CimInstance Win32_OperatingSystem -ErrorAction Stop
    Line "caption"    $os.Caption
    Line "version"    $os.Version
    Line "build"      $os.BuildNumber
    Line "arch"       $os.OSArchitecture
    Line "installed"  $os.InstallDate
    Line "lastBoot"   $os.LastBootUpTime
} catch { Line "error" $_.Exception.Message }
try {
    $cs = Get-CimInstance Win32_ComputerSystem -ErrorAction Stop
    Line "manufacturer" $cs.Manufacturer
    Line "model"        $cs.Model
    Line "ram_GB"       ([math]::Round($cs.TotalPhysicalMemory / 1GB, 1))
    Line "cpu"          ((Get-CimInstance Win32_Processor | Select-Object -First 1).Name)
    Line "cores"        ((Get-CimInstance Win32_Processor | Measure-Object -Property NumberOfLogicalProcessors -Sum).Sum)
} catch { }

Sec "2. PYTHON  (most important section)"
# Where python could be, including conda and the Windows Store shim.
$cands = @()
foreach ($n in @('python', 'python3', 'py')) {
    $c = Get-Command $n -ErrorAction SilentlyContinue
    if ($c) { $cands += $c.Source }
}
$cands += @(
    "$env:LOCALAPPDATA\Programs\Python",
    "$env:ProgramFiles\Python*",
    "$env:USERPROFILE\anaconda3",
    "$env:USERPROFILE\miniconda3",
    "C:\ProgramData\anaconda3",
    "C:\ProgramData\miniconda3"
)
$seen = @{}
foreach ($p in $cands) {
    foreach ($hit in @(Get-Item $p -ErrorAction SilentlyContinue)) {
        $exe = if ($hit.PSIsContainer) { Join-Path $hit.FullName 'python.exe' } else { $hit.FullName }
        if (-not (Test-Path $exe)) { continue }
        if ($seen.ContainsKey($exe)) { continue }
        $seen[$exe] = $true
        # The Microsoft Store ships a 0-byte "python.exe" alias under WindowsApps that
        # opens the Store instead of running Python. Calling it writes a Store message
        # to stderr, which PowerShell 5 surfaces as NativeCommandError and which then
        # pollutes this report with raw error text (seen on DESKTOP-LOTFUFQ). Detect it
        # by path and never invoke it.
        if ($exe -match '\\WindowsApps\\') {
            Write-Host ("  STUB   " + "Microsoft Store alias - NOT a real python".PadRight(18) + "  " + $exe)
            continue
        }
        # `cmd /c ... 2>nul` keeps a failing interpreter from dumping stderr into the report.
        $v = (cmd /c "`"$exe`" --version 2>nul" | Out-String).Trim()
        if ($v -match '^Python ') {
            Write-Host ("  FOUND  " + $v.PadRight(18) + "  " + $exe)
        } else {
            Write-Host ("  FOUND  " + "(version failed)".PadRight(18) + "  " + $exe)
        }
    }
}
if ($seen.Count -eq 0) { Write-Host "  NO PYTHON FOUND" }
Write-Host "  NOTE: this project requires python >= 3.10."

Sec "3. NODE / NPM  (needed by the 3D console)"
foreach ($n in @('node', 'npm')) {
    $c = Get-Command $n -ErrorAction SilentlyContinue
    if ($c) {
        try { Line $n ((& $n --version 2>&1 | Out-String).Trim() + "   " + $c.Source) }
        catch { Line $n ("present: " + $c.Source) }
    } else { Line $n "NOT FOUND" }
}

Sec "4. GPU  (decides whether the 3D view can render)"
try {
    Get-CimInstance Win32_VideoController -ErrorAction Stop | ForEach-Object {
        Write-Host ("  NAME      : " + $_.Name)
        Write-Host ("  DRIVER    : " + $_.DriverVersion + "   date=" + $_.DriverDate)
        if ($_.AdapterRAM) { Write-Host ("  VRAM(rep) : " + [math]::Round($_.AdapterRAM / 1MB) + " MB  (WMI often caps at 4096)") }
        Write-Host ""
    }
} catch { Write-Host ("  error: " + $_.Exception.Message) }
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
    Write-Host "  --- nvidia-smi ---"
    try { & nvidia-smi --query-gpu=name,driver_version,memory.total,compute_cap --format=csv 2>&1 | ForEach-Object { Write-Host ("    " + $_) } }
    catch { Write-Host "    nvidia-smi failed" }
} else { Write-Host "  nvidia-smi: NOT FOUND (no NVIDIA driver, or not on PATH)" }

Sec "5. DISK"
try {
    Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" -ErrorAction Stop | ForEach-Object {
        $free = [math]::Round($_.FreeSpace / 1GB, 1)
        $size = [math]::Round($_.Size / 1GB, 1)
        Write-Host ("  " + $_.DeviceID.PadRight(6) + " total=" + ($size.ToString().PadLeft(8)) + " GB   free=" + ($free.ToString().PadLeft(8)) + " GB   label=" + $_.VolumeName)
    }
} catch { }
Write-Host "  --- physical disks ---"
try {
    Get-CimInstance Win32_DiskDrive -ErrorAction Stop | ForEach-Object {
        Write-Host ("  " + $_.Model + "   " + [math]::Round($_.Size / 1GB) + " GB   " + $_.InterfaceType)
    }
} catch { }

Sec "6. WSL  (VERY IMPORTANT: decides which recon script applies)"
$wsl = Get-Command wsl -ErrorAction SilentlyContinue
if ($wsl) {
    Line "wsl.exe" $wsl.Source
    Write-Host "  --- installed distributions ---"
    try {
        # wsl.exe writes UTF-16LE. Read through cmd.exe and strip NUL bytes, or the
        # output shows up as "N A M E" (NUL interleaved between every character).
        $raw = (cmd /c "wsl -l -v" 2>&1 | Out-String)
        $clean = $raw -replace "`0", ""
        foreach ($l in ($clean -split "`r?`n")) {
            if ($l.Trim().Length -gt 0) { Write-Host ("    " + $l.TrimEnd()) }
        }
        Write-Host "  >>> If a distribution is listed with VERSION 2, then bash IS available"
        Write-Host "      and recon-offline-env.sh can be used instead of this script."
    } catch { Write-Host "    wsl -l -v failed (no distribution installed?)" }
} else {
    Write-Host "  wsl.exe NOT FOUND  -> NO bash on this machine by default."
    Write-Host "  >>> Use THIS script (recon-windows.ps1). The bash recon script will not run here."
}

Sec "7. NETWORK"
try {
    Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
        Where-Object { $_.IPAddress -ne '127.0.0.1' } |
        ForEach-Object { Write-Host ("  " + $_.InterfaceAlias.PadRight(34) + " " + $_.IPAddress + "/" + $_.PrefixLength) }
} catch {
    try { ipconfig | Select-String 'IPv4' | ForEach-Object { Write-Host ("  " + $_.Line.Trim()) } } catch { }
}
Write-Host "  --- listening ports (top 20) ---"
try {
    Get-NetTCPConnection -State Listen -ErrorAction Stop |
        Sort-Object LocalPort | Select-Object -First 20 |
        ForEach-Object { Write-Host ("    TCP " + ($_.LocalAddress + ":" + $_.LocalPort).PadRight(26) + " pid=" + $_.OwningProcess) }
} catch { }

Sec "8. BROWSERS  (the console is a web page)"
foreach ($b in @('msedge', 'chrome', 'firefox')) {
    $c = Get-Command $b -ErrorAction SilentlyContinue
    if (-not $c) {
        $guess = @{
            'msedge'  = "$env:ProgramFiles (x86)\Microsoft\Edge\Application\msedge.exe"
            'chrome'  = "$env:ProgramFiles\Google\Chrome\Application\chrome.exe"
            'firefox' = "$env:ProgramFiles\Mozilla Firefox\firefox.exe"
        }[$b]
        if ($guess -and (Test-Path $guess)) { $c = Get-Item $guess }
    }
    if ($c) {
        $exe = if ($c.PSIsContainer) { Join-Path $c.FullName 'msedge.exe' } else { $c.Source }
        try { Write-Host ("  " + $b.PadRight(9) + " " + ((& $exe --version 2>&1 | Out-String).Trim())) }
        catch { Write-Host ("  " + $b.PadRight(9) + " present") }
    } else { Write-Host ("  " + $b.PadRight(9) + " NOT FOUND") }
}

Sec "9. GIT / SSH / TRANSFER TOOLS"
foreach ($t in @('git', 'ssh', 'scp', 'curl', 'tar', '7z')) {
    $c = Get-Command $t -ErrorAction SilentlyContinue
    if ($c) { Write-Host ("  " + $t.PadRight(6) + " OK   " + $c.Source) } else { Write-Host ("  " + $t.PadRight(6) + " MISSING") }
}

Sec "10. ANYTHING OF OURS ALREADY HERE?"
foreach ($root in @("$env:USERPROFILE", 'C:\', 'D:\')) {
    if (-not (Test-Path $root)) { continue }
    try {
        $hits = Get-ChildItem $root -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match 'uav|swarm|px4|gazebo|jetson' } |
            Select-Object -First 8
        foreach ($h in $hits) { Write-Host ("  " + $h.FullName) }
    } catch { }
}

Sec "11. CAPABILITY RATING AND SUGGESTED ROLE"
# Mirrors section 11 of recon-offline-env.sh so Windows and Linux machines can be
# compared on the same scale. All thresholds come from measurements in this project:
#   * Simulator: the camera-equipped 3-vehicle SITL ran at RTF 0.84-0.94 on an
#     RTX 4050; WITHOUT the GPU-adapter variable it collapsed to 0.175, and an
#     integrated-only machine lands in that same band -- below the 0.20 floor.
#     So: no discrete GPU => no usable PX4/Gazebo simulation.
#   * Runtime: pyproject.toml declares requires-python >= 3.10.
#   * Frontend: swarm-console is static; simulation-3d needs WebGL. Very old
#     integrated drivers (e.g. Intel 2018) are a white-screen risk.

# --- python >= 3.10 ? ---
# Only a REAL interpreter counts. The Store alias must not be invoked (it opens the
# Store and writes a message to stderr that would land in this report).
$pyMajor = -1; $pyMinor = -1; $pyExe = $null
$pc = Get-Command python -ErrorAction SilentlyContinue
if ($pc -and $pc.Source -notmatch '\\WindowsApps\\') {
    $pyExe = $pc.Source
    $v = (cmd /c "`"$pyExe`" -c `"import sys;print('%d.%d'%sys.version_info[:2])`" 2>nul" | Out-String).Trim()
    if ($v -match '^(\d+)\.(\d+)$') { $pyMajor = [int]$Matches[1]; $pyMinor = [int]$Matches[2] }
}
$pyOk = ($pyMajor -gt 3) -or ($pyMajor -eq 3 -and $pyMinor -ge 10)
# Serving the frontends only needs "some real python 3" (3.8 is fine for http.server),
# which is a weaker requirement than running Runtime.
$pyServeOk = ($pyMajor -ge 3)

# --- discrete GPU ? ---
$gpus = @()
try { $gpus = @(Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue | ForEach-Object { $_.Name }) } catch { }
$hasNvidia = @($gpus | Where-Object { $_ -match 'NVIDIA|GeForce|Quadro|RTX|GTX|Tesla' }).Count -gt 0
$hasAmd    = @($gpus | Where-Object { $_ -match 'Radeon|AMD' }).Count -gt 0
$hasDgpu   = $hasNvidia -or $hasAmd
$onlyIntel = ($gpus.Count -gt 0) -and (-not $hasDgpu)

# --- memory ---
$ramGb = 0
try { $ramGb = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 0) } catch { }

# --- browser ? ---
$hasBrowser = $false
foreach ($b in @('msedge', 'chrome', 'firefox')) {
    if (Get-Command $b -ErrorAction SilentlyContinue) { $hasBrowser = $true; break }
}
if (-not $hasBrowser) {
    $cands = @(
        "$env:ProgramFiles (x86)\Microsoft\Edge\Application\msedge.exe",
        "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
        "$env:LOCALAPPDATA\Microsoft\Edge\Application\msedge.exe",
        "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
        "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
        "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe",
        "$env:ProgramFiles\Mozilla Firefox\firefox.exe",
        "${env:ProgramFiles(x86)}\Mozilla Firefox\firefox.exe"
    )
    foreach ($c in $cands) { if (Test-Path $c) { $hasBrowser = $true; break } }
}
# Last resort: the Windows "App Paths" registry keys survive path changes and
# per-user installs. This is how a stripped image with a moved browser still shows up.
if (-not $hasBrowser) {
    foreach ($k in @('msedge.exe', 'chrome.exe', 'firefox.exe')) {
        $rk = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\$k"
        if (Test-Path $rk) { $hasBrowser = $true; break }
    }
}
if (-not $hasBrowser) {
    # Windows 10 always ships *some* Edge; if nothing was found, say so explicitly
    # rather than silently concluding "no browser".
    if (Test-Path 'C:\Windows\SystemApps\Microsoft.MicrosoftEdge_8wekyb3d8bbwe') { $hasBrowser = $true }
}

# --- WSL ? (a WSL window would let the bash recon run here too) ---
$hasWsl2 = $false
if (Get-Command wsl -ErrorAction SilentlyContinue) {
    try {
        $raw = ((cmd /c "wsl -l -v" 2>&1 | Out-String) -replace "`0", "")
        if ($raw -match 'VERSION' -and $raw -match '\b2\b') { $hasWsl2 = $true }
    } catch { }
}

Write-Host ("  facts: python=" + $pyMajor + "." + $pyMinor + " (>=3.10? " + $pyOk + ")  RAM=" + $ramGb + "GB")
Write-Host ("         GPU: " + $(if ($gpus.Count) { $gpus -join ' | ' } else { '(none detected)' }))
Write-Host ""
Write-Host "  --- capability ---"
if ($hasDgpu -and $ramGb -ge 16) {
    Write-Host "  [YES] run the simulator (PX4 + Gazebo, 3-vehicle camera build) -- discrete GPU + enough RAM"
} elseif ($onlyIntel) {
    Write-Host "  [NO]  run the simulator -- integrated GPU only; expect RTF near 0.18 (floor is 0.20)"
} else {
    Write-Host "  [NO]  run the simulator -- no discrete GPU detected or RAM below 16 GB"
}
if ($pyOk) {
    Write-Host ("  [YES] run Runtime (uav_runtime) -- python " + $pyMajor + "." + $pyMinor + " satisfies >=3.10")
} else {
    Write-Host "  [NO]  run Runtime -- python >= 3.10 required (Ubuntu 20.04 ships 3.8; Windows needs 3.10+)"
}
if ($pyServeOk) {
    Write-Host ("  [YES] serve the frontends -- python " + $pyMajor + "." + $pyMinor + " can run -m http.server")
} else {
    Write-Host "  [NO]  serve the frontends -- no real python found (the Microsoft Store alias does not count)"
    Write-Host "        workaround: serve from another machine, or drop in the portable python zip"
}
if ($hasBrowser) {
    Write-Host "  [YES] display the console -- a browser is present (3D still needs working WebGL)"
} else {
    Write-Host "  [!]   display the console -- NO browser found; install one or use another machine"
}
if ($hasDgpu) {
    Write-Host "  [YES] act as a simulated unmanned platform -- could host PX4 SITL"
}
if ($hasWsl2) {
    Write-Host "  [YES] has WSL2 -- the bash recon (recon-offline-env.sh) can also run here"
}

Write-Host ""
Write-Host "  --- suggested role, in priority order ---"
if ($hasDgpu -and $ramGb -ge 16) {
    Write-Host "    1) simulator host (PX4+Gazebo)   2) frontend display   3) Runtime (if python>=3.10)"
} elseif ($hasBrowser) {
    Write-Host "    1) frontend display   2) Runtime (if python>=3.10)   3) add a discrete GPU to become a sim host"
} else {
    Write-Host "    1) storage / relay   2) add a browser to use it as a console display"
}
Write-Host ""
Write-Host "  NOTE: an integrated GPU is fine for the 2D console; the risk is only in the 3D view."
Write-Host "  Compare against the Linux machines using section 11 of recon-offline-env.sh."

Sec "END"
Write-Host "  Critical sections: 2 (Python), 5 (Disk), 6 (WSL), 11 (rating)."
Write-Host "  To save: powershell -NoProfile -ExecutionPolicy Bypass -File recon-windows.ps1 *> recon-win.txt"
