#!/bin/bash
# Raven AI initializer — by ssrjkk
set -e

echo "=== Raven AI Initialization (by ssrjkk) ==="

mkdir -p ./data ./workspace

if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        cp .env.example .env
        echo "[+] Created .env from .env.example"
        echo "[!] Edit .env and add your API keys (TELEGRAM_BOT_TOKEN, etc.)"
    else
        echo "[!] No .env.example found — create .env manually"
    fi
fi

if [ ! -d web/dist ]; then
    echo "[i] Web dashboard not built — run: cd web && npm ci && npm run build"
fi

echo "[+] Done. Run: docker compose --profile minimal up"
echo "    or locally: pip install -e . && raven start"
