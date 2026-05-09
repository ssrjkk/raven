#!/usr/bin/env bash
set -euo pipefail

echo "🐦 Raven AI — Docker Launch"
echo "=========================="

cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
    echo "Creating .env from .env.example..."
    cp .env.example .env
    echo "⚠️  Edit .env with your API keys before running"
fi

docker compose -f deploy/docker-compose.yml up --build -d
echo "✅ Raven AI running at http://localhost:18888"
