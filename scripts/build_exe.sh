#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(dirname "$0")/.."

echo "🐦 Raven AI — Build Executable"
echo "================================"

echo ""
echo "[1/3] Installing build dependencies..."
pip install pyinstaller

ICO="$PROJECT_ROOT/resources/raven.ico"
if [ -f "$ICO" ]; then
    echo "  ✅ Found mascot icon: $ICO"
else
    echo "  ⚠️  No mascot icon found at $ICO"
    echo "  → The binary will use the default PyInstaller icon"
    echo "  → Place your .ico file at resources/raven.ico and rebuild"
fi

echo ""
echo "[2/3] Building raven executable..."
cd "$PROJECT_ROOT"
pyinstaller --clean raven.spec
cd - > /dev/null

EXE="$PROJECT_ROOT/dist/raven/raven"
if [ -f "$EXE" ]; then
    echo ""
    echo "[3/3] ✅ Build complete!"
    echo "  → Executable: $EXE"
    echo "  → Size: $(du -h "$EXE" | cut -f1)"
    echo ""
    echo "Run: ./dist/raven/raven start"
else
    echo "❌ Build failed" >&2
    exit 1
fi
