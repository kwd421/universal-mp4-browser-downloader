param(
    [string]$ExePath,
    [string]$BuildNumber = "105",
    [int]$TimeoutMs = 15000
)

$ErrorActionPreference = "Stop"

if (-not $ExePath) {
    $candidates = @(
        (Join-Path $PSScriptRoot "..\dist\ClipFlow-1.0.6.exe"),
        (Join-Path $PSScriptRoot "..\dist\ClipFlow.exe")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            $ExePath = (Resolve-Path $candidate).Path
            break
        }
    }
}

if (-not $ExePath -or -not (Test-Path $ExePath)) {
    Write-Output "startup_verify_missing_exe=1"
    exit 1
}

Get-Process ClipFlow* -ErrorAction SilentlyContinue | ForEach-Object {
    Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Milliseconds 500

$env:CLIPFLOW_BUILD_NUMBER = $BuildNumber
$sw = [System.Diagnostics.Stopwatch]::StartNew()
$proc = Start-Process -FilePath $ExePath -PassThru
$hungStreak = 0
$maxHungStreak = 0
$seenProcess = $false

while ($sw.ElapsedMilliseconds -lt $TimeoutMs) {
    Start-Sleep -Milliseconds 400
    $running = Get-Process -Id $proc.Id -ErrorAction SilentlyContinue
    if (-not $running) {
        break
    }
    $seenProcess = $true
    $family = @(Get-Process -Name ($running.ProcessName) -ErrorAction SilentlyContinue)
    if (-not $family) {
        continue
    }
    if ($family | Where-Object { -not $_.Responding }) {
        $hungStreak += 1
        if ($hungStreak -gt $maxHungStreak) {
            $maxHungStreak = $hungStreak
        }
    }
    else {
        $hungStreak = 0
    }
}

if ($proc -and -not $proc.HasExited) {
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
}
Get-Process ClipFlow* -ErrorAction SilentlyContinue | ForEach-Object {
    Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
}

Write-Output "startup_verify_exe=$ExePath"
Write-Output "startup_verify_build=$BuildNumber"
Write-Output "startup_verify_seen_process=$seenProcess"
Write-Output "startup_verify_max_hung_streak=$maxHungStreak"

if (-not $seenProcess) {
    exit 1
}
if ($maxHungStreak -ge 4) {
    exit 1
}
exit 0