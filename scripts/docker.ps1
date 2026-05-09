#!/usr/bin/env pwsh
$ErrorActionPreference = "Stop"

Write-Host "🐦 Raven AI — Docker Launch" -ForegroundColor Cyan
Write-Host "==========================" -ForegroundColor Cyan

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "⚠️  Edit .env with your API keys before running" -ForegroundColor Yellow
}

docker compose -f deploy/docker-compose.yml up --build -d
Write-Host "✅ Raven AI running at http://localhost:18888" -ForegroundColor Green
