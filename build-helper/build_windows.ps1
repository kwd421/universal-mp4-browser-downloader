$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

python -m pip install -r requirements.txt
python -m unittest discover -s test -p "test_*.py" -v
python -m PyInstaller build-helper\UniversalMP4BrowserDownloader.spec --noconfirm
Copy-Item -Force dist\UniversalMP4BrowserDownloader.exe UniversalMP4BrowserDownloader.exe
