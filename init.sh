#!/bin/bash
set -e

echo "=== Raven AI Initialization ==="

mkdir -p ./data/db ./data/logs ./workspace ./deploy/prometheus

if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        cp .env.example .env
        echo "[+] Created .env from .env.example"
        echo "[!] Edit .env and add your API keys (TELEGRAM_BOT_TOKEN, etc.)"
    else
        echo "[!] No .env.example found — create .env manually"
    fi
fi

echo "[+] Done. Run: docker compose --profile minimal up"
