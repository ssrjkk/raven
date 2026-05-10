#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Build Raven AI Windows executable via PyInstaller
.DESCRIPTION
    Packages the entire Raven AI CLI into a single raven.exe
    Place your mascot icon at resources/raven.ico before building
#>
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot

Write-Host "🐦 Raven AI — Build Windows Executable" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# Check Python
$py = (Get-Command python -ErrorAction SilentlyContinue)
if (-not $py) {
    Write-Host "❌ Python not found. Install Python 3.12+ first." -ForegroundColor Red
    exit 1
}

Write-Host "`n[1/3] Installing build dependencies..." -ForegroundColor Yellow
pip install pyinstaller
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Failed to install pyinstaller" -ForegroundColor Red
    exit 1
}

# Check for mascot icon
$ico = Join-Path $ProjectRoot "resources" "raven.ico"
if (Test-Path $ico) {
    Write-Host "  ✅ Found mascot icon: $ico" -ForegroundColor Green
} else {
    Write-Host "  ⚠️  No mascot icon found at $ico" -ForegroundColor Yellow
    Write-Host "  → The .exe will use the default PyInstaller icon" -ForegroundColor Yellow
    Write-Host "  → Place your .ico file at resources/raven.ico and rebuild" -ForegroundColor Yellow
}

Write-Host "`n[2/3] Building raven.exe..." -ForegroundColor Yellow
$spec = Join-Path $ProjectRoot "raven.spec"
Push-Location $ProjectRoot
pyinstaller --clean $spec
Pop-Location

if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Build failed" -ForegroundColor Red
    exit 1
}

$exe = Join-Path $ProjectRoot "dist" "raven" "raven.exe"
if (Test-Path $exe) {
    Write-Host "`n[3/3] ✅ Build complete!" -ForegroundColor Green
    Write-Host "  → Executable: $exe" -ForegroundColor Cyan
    Write-Host "  → Size: $((Get-Item $exe).Length / 1MB -as [int]) MB" -ForegroundColor Cyan
    Write-Host "`nRun: .\dist\raven\raven.exe start" -ForegroundColor Cyan
} else {
    Write-Host "❌ Build failed: raven.exe not found at $exe" -ForegroundColor Red
    exit 1
}
