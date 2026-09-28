#!/usr/bin/env bash
# Raven AI setup — by ssrjkk
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RAVEN_DIR="${RAVEN_DIR:-$HOME/.raven}"

echo "🐦 Raven AI — Setup (by ssrjkk)"
echo "=============================="

echo ""
echo "[1/5] Installing Python backend (editable + dev extras)..."
python -m pip install -e "$ROOT[dev]"

echo ""
echo "[2/5] Building web dashboard..."
if [ -f "$ROOT/web/package.json" ]; then
    (cd "$ROOT/web" && npm ci && npm run build)
else
    echo "  [!] web/ not found, skipping"
fi

echo ""
echo "[3/5] Generating icons..."
python "$ROOT/scripts/make_icon.py"
python "$ROOT/scripts/make_extension_icons.py"

echo ""
echo "[4/5] Preparing runtime directories..."
mkdir -p "$ROOT/data" "$ROOT/workspace" "$RAVEN_DIR"
if [ ! -f "$ROOT/.env" ] && [ -f "$ROOT/.env.example" ]; then
    cp "$ROOT/.env.example" "$ROOT/.env"
    echo "  [+] Created .env from .env.example — add your API keys"
fi

echo ""
echo "[5/5] Verification gate..."
python "$ROOT/scripts/check_all.py" --quick

echo ""
echo "✅ Setup complete! Run: raven start   (or: raven onboard)"

