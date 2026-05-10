#!/usr/bin/env bash
set -euo pipefail

RAVEN_DIR="${RAVEN_DIR:-$HOME/.raven}"
WEB_DIR="$(dirname "$0")/../web"
DESKTOP_DIR="$(dirname "$0")/../desktop"

echo "🐦 Raven AI — Setup"
echo "===================="

# Python backend
echo ""
echo "[1/5] Installing Python backend..."
pip install -e "$(dirname "$0")/.."

# Rust daemon
echo ""
echo "[2/5] Building Rust daemon..."
DAEMON_DIR="$(dirname "$0")/../daemon"
if [ -f "$DAEMON_DIR/Cargo.toml" ]; then
    cd "$DAEMON_DIR"
    cargo build --release
    cd - > /dev/null
    echo "  ✅ ravend built at $DAEMON_DIR/target/release/ravend"
else
    echo "  ⚠️  daemon/ not found, skipping"
fi

# TypeScript web UI
echo ""
echo "[3/5] Installing web UI..."
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
echo "[4/5] Building desktop app..."
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
echo "[5/5] Creating config directory..."
mkdir -p "$RAVEN_DIR"

echo ""
echo "✅ Setup complete!"
echo "Run: raven start"
