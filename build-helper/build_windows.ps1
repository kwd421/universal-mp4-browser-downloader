param(
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"

function Invoke-PythonStep {
    param(
        [string]$Label,
        [string[]]$Arguments
    )
    & python @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE"
    }
}

function Install-Requirements {
    Invoke-PythonStep "pip install" @("-m", "pip", "install", "-r", "requirements.txt")
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

try {
    Install-Requirements
}
catch {
    Write-Host "Pinned requirements failed; retrying with latest PyPI yt-dlp for CI/release builds."
    $ciRequirements = Join-Path $env:TEMP "clipflow-requirements-ci.txt"
    (Get-Content "requirements.txt") -replace '^yt-dlp==.*$', 'yt-dlp' | Set-Content $ciRequirements -Encoding utf8
    Invoke-PythonStep "pip install (CI fallback)" @("-m", "pip", "install", "-r", $ciRequirements)
}

if (-not $SkipTests) {
    Invoke-PythonStep "unit tests" @("-m", "unittest", "discover", "-s", "test", "-p", "test_*.py", "-v")
}

Invoke-PythonStep "PyInstaller" @("-m", "PyInstaller", "build-helper\ClipFlow.spec", "--noconfirm")
$builtExe = Join-Path $repoRoot "dist\ClipFlow.exe"
if (-not (Test-Path $builtExe)) {
    throw "Built executable not found: $builtExe"
}
Copy-Item -Force $builtExe (Join-Path $repoRoot "ClipFlow.exe")