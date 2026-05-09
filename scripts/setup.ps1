#!/usr/bin/env pwsh
$ErrorActionPreference = "Stop"

$RavenDir = if ($env:RAVEN_DIR) { $env:RAVEN_DIR } else { "$HOME\.raven" }
$ProjectRoot = Split-Path -Parent $PSScriptRoot

Write-Host "🐦 Raven AI — Setup" -ForegroundColor Cyan
Write-Host "====================" -ForegroundColor Cyan

Write-Host "`n[1/4] Installing Python backend..." -ForegroundColor Yellow
pip install -e "$ProjectRoot"
if ($LASTEXITCODE -ne 0) { Write-Host "  ❌ pip install failed" -ForegroundColor Red; exit 1 }

Write-Host "`n[2/4] Installing web UI..." -ForegroundColor Yellow
$WebDir = Join-Path $ProjectRoot "web"
if (Test-Path "$WebDir\package.json") {
    Push-Location $WebDir
    npm install
    if ($LASTEXITCODE -eq 0) { npm run build }
    Pop-Location
} else {
    Write-Host "  ⚠️  web/ not found" -ForegroundColor Yellow
}

Write-Host "`n[3/4] Building desktop app..." -ForegroundColor Yellow
$DesktopDir = Join-Path $ProjectRoot "desktop"
if (Test-Path "$DesktopDir\package.json") {
    Push-Location $DesktopDir
    npm install
    if ($LASTEXITCODE -eq 0) { npm run build }
    Pop-Location
} else {
    Write-Host "  ⚠️  desktop/ not found" -ForegroundColor Yellow
}

Write-Host "`n[4/4] Creating config directory..." -ForegroundColor Yellow
New-Item -ItemType Directory -Force -Path $RavenDir | Out-Null

Write-Host "`n✅ Setup complete!" -ForegroundColor Green
Write-Host "Run: raven start" -ForegroundColor Cyan
