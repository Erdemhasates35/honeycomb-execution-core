#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

mkdir -p logs runtime

pkill -f "uvicorn nexus_testnet_bridge:app" 2>/dev/null || true

termux-wake-lock 2>/dev/null || true

nohup python -m uvicorn nexus_testnet_bridge:app \
  --host 0.0.0.0 \
  --port 8100 \
  --workers 1 \
  > logs/nexus_bridge.log 2>&1 &

echo $! > runtime/nexus_bridge.pid

sleep 2

echo
echo "=== BRIDGE ==="
curl -fsS http://127.0.0.1:8100/health
echo
echo

echo "=== ENGINE ==="
curl -fsS http://127.0.0.1:8000/health || true
echo
echo

echo "=== BINANCE TESTNET TIME ==="
curl -fsS http://127.0.0.1:8100/testnet/time
echo
echo

echo "=== ENDPOINTS ==="
echo "http://127.0.0.1:8100/"
echo "http://127.0.0.1:8100/health"
echo "http://127.0.0.1:8100/status"
echo "http://127.0.0.1:8100/testnet/account"
echo "http://127.0.0.1:8100/testnet/positions"
echo "http://127.0.0.1:8100/docs"
