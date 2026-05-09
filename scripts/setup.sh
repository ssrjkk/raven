#!/usr/bin/env bash
set -euo pipefail

RAVEN_DIR="${RAVEN_DIR:-$HOME/.raven}"
WEB_DIR="$(dirname "$0")/../web"
DESKTOP_DIR="$(dirname "$0")/../desktop"

echo "🐦 Raven AI — Setup"
echo "===================="

# Python backend
echo ""
echo "[1/4] Installing Python backend..."
pip install -e "$(dirname "$0")/.."

# TypeScript web UI
echo ""
echo "[2/4] Installing web UI..."
if [ -f "$WEB_DIR/package.json" ]; then
    cd "$WEB_DIR"
    npm install
    npm run build
    cd - > /dev/null
else
    echo "  ⚠️  web/ not found, skipping"
fi

# Electron desktop
echo ""
echo "[3/4] Building desktop app..."
if [ -f "$DESKTOP_DIR/package.json" ]; then
    cd "$DESKTOP_DIR"
    npm install
    npm run build
    cd - > /dev/null
else
    echo "  ⚠️  desktop/ not found, skipping"
fi

# Config dir
echo ""
echo "[4/4] Creating config directory..."
mkdir -p "$RAVEN_DIR"

echo ""
echo "✅ Setup complete!"
echo "Run: raven start"
