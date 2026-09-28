#!/usr/bin/env pwsh
# Raven AI setup — by ssrjkk
$ErrorActionPreference = "Stop"

$RavenDir = if ($env:RAVEN_DIR) { $env:RAVEN_DIR } else { "$HOME\.raven" }
$ProjectRoot = Split-Path -Parent $PSScriptRoot

Write-Host "🐦 Raven AI — Setup (by ssrjkk)" -ForegroundColor Cyan
Write-Host "==============================" -ForegroundColor Cyan

Write-Host "`n[1/5] Installing Python backend (editable + dev extras)..." -ForegroundColor Yellow
pip install -e "$ProjectRoot[dev]"
if ($LASTEXITCODE -ne 0) { Write-Host "  ❌ pip install failed" -ForegroundColor Red; exit 1 }

Write-Host "`n[2/5] Building web dashboard..." -ForegroundColor Yellow
$WebDir = Join-Path $ProjectRoot "web"
if (Test-Path "$WebDir\package.json") {
    Push-Location $WebDir
    npm ci
    if ($LASTEXITCODE -eq 0) { npm run build }
    Pop-Location
} else {
    Write-Host "  ⚠️  web/ not found" -ForegroundColor Yellow
}

Write-Host "`n[3/5] Generating icons..." -ForegroundColor Yellow
python (Join-Path $ProjectRoot "scripts\make_icon.py")
python (Join-Path $ProjectRoot "scripts\make_extension_icons.py")

Write-Host "`n[4/5] Preparing runtime directories..." -ForegroundColor Yellow
New-Item -ItemType Directory -Force -Path $RavenDir | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot "data") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot "workspace") | Out-Null
$EnvFile = Join-Path $ProjectRoot ".env"
if (-not (Test-Path $EnvFile) -and (Test-Path "$ProjectRoot\.env.example")) {
    Copy-Item "$ProjectRoot\.env.example" $EnvFile
    Write-Host "  [+] Created .env from .env.example — add your API keys" -ForegroundColor Green
}

Write-Host "`n[5/5] Verification gate (ruff + mypy + imports)..." -ForegroundColor Yellow
python (Join-Path $ProjectRoot "scripts\check_all.py") --quick

Write-Host "`n✅ Setup complete!" -ForegroundColor Green
Write-Host "Run: raven start   (or: raven onboard)" -ForegroundColor Cyan
