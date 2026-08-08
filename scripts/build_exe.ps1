# Builds the Raven Desktop EXE (gateway + bundled web UI).
# Prereqs: npm installed, python venv with project deps + pyinstaller installed.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "== Step 1/3: building web frontend =="
Push-Location web
npm run build
if ($LASTEXITCODE -ne 0) { throw "web build failed" }
Pop-Location

Write-Host "== Step 2/3: generating app icon =="
python scripts/make_icon.py

Write-Host "== Step 3/3: building EXE with PyInstaller =="
python -m PyInstaller --noconfirm --clean --distpath packaging\dist --workpath packaging\build scripts/raven.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed" }

$Exe = Join-Path $Root "packaging\dist\Raven.exe"
Write-Host ""
Write-Host "Build complete: $Exe"
Write-Host "Run it to start Raven and open the web UI."
