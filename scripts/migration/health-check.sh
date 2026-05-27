#!/usr/bin/env bash
# Validate migration health — checks feature flags, service health, and NATS streams
set -euo pipefail

echo "=== Migration Health Check ==="

# 1. Feature flags
echo ""
echo "--- Feature Flags ---"
for flag in $(env | grep "^FF_" | cut -d= -f1); do
  val="${!flag}"
  status="✅" 
  [ "$val" == "true" ] || status="⏹️"
  echo "  $status $flag=$val"
done

# 2. Service health
echo ""
echo "--- Service Health ---"
for svc in gateway auth:8001 agent-core:8002 monitor-engine:8003 rag-service:8004 task-engine:8005 code-service:8006; do
  name="${svc%%:*}"
  port="${svc##*:}"
  status=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:$port/health" 2>/dev/null || echo "000")
  if [ "$status" == "200" ]; then
    echo "  ✅ $name (:$port) healthy"
  else
    echo "  ❌ $name (:$port) status=$status"
  fi
done

# 3. NATS streams
echo ""
echo "--- NATS Streams ---"
python deploy/nats/nats-stream-manager.py verify 2>/dev/null || echo "  ⚠️  NATS not reachable"

echo ""
echo "=== Health check complete ==="
