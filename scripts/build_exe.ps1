#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Build Raven AI Windows executable via PyInstaller
.DESCRIPTION
    Packages the entire Raven AI CLI + AI-OS-MVP bridge into a single raven.exe
#>
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot

Write-Host "Raven AI -- Build Windows Executable" -ForegroundColor Cyan
Write-Host "=====================================" -ForegroundColor Cyan

$py = (Get-Command python -ErrorAction SilentlyContinue)
if (-not $py) {
    Write-Host "Python not found. Install Python 3.11+ first." -ForegroundColor Red
    exit 1
}

Write-Host "[1/3] Installing build dependencies..." -ForegroundColor Yellow
pip install pyinstaller
if ($LASTEXITCODE -ne 0) {
    Write-Host "Failed to install pyinstaller" -ForegroundColor Red
    exit 1
}

Write-Host "[2/3] Building raven.exe..." -ForegroundColor Yellow
$spec = Join-Path $ProjectRoot "raven.spec"
Push-Location $ProjectRoot
pyinstaller --clean $spec
Pop-Location

if ($LASTEXITCODE -ne 0) {
    Write-Host "Build failed" -ForegroundColor Red
    exit 1
}

$exe = Join-Path $ProjectRoot "dist" "raven" "raven.exe"
if (Test-Path $exe) {
    Write-Host "[3/3] Build complete!" -ForegroundColor Green
    Write-Host "  Executable: $exe" -ForegroundColor Cyan
    Write-Host "  Size: $((Get-Item $exe).Length / 1MB -as [int]) MB" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Run: .\dist\raven\raven.exe start" -ForegroundColor Cyan
    Write-Host "Contacts:" -ForegroundColor Cyan
    Write-Host "  Telegram: @ssrjkk" -ForegroundColor Cyan
    Write-Host "  GitHub: github.com/ssrjkk" -ForegroundColor Cyan
    Write-Host "  Email: ray013lefe@gmail.com" -ForegroundColor Cyan
} else {
    Write-Host "Build failed: raven.exe not found at $exe" -ForegroundColor Red
    exit 1
}
