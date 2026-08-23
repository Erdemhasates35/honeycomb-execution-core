#!/data/data/com.termux/files/usr/bin/bash
# Honeycomb deterministic TESTNET launcher: engine 8000 + bridge 8100.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
mkdir -p logs runtime sockets
load_env(){
  [ -f .env ] || return 0
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%$'\r'}"
    [[ "$line" =~ ^[[:space:]]*# ]] && continue
    [[ "$line" =~ ^[[:space:]]*$ ]] && continue
    if [[ "$line" =~ ^[[:space:]]*([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]]; then
      key="${BASH_REMATCH[1]}"; value="${BASH_REMATCH[2]}"
      value="${value%$'\r'}"
      if [[ "$value" =~ ^\".*\"$ || "$value" =~ ^\'.*\'$ ]]; then value="${value:1:${#value}-2}"; fi
      export "$key=$value"
    fi
  done < .env
}
load_env
export HONEYCOMB_MODE=TESTNET TESTNET_PORT="${TESTNET_PORT:-8000}" ENGINE_URL="http://127.0.0.1:${TESTNET_PORT}"
termux-wake-lock 2>/dev/null || true
stop(){ for f in runtime/testnet-engine.pid runtime/testnet-bridge.pid; do [ -f "$f" ] && kill "$(cat "$f")" 2>/dev/null || true; done; }
stop
nohup python engine_testnet.py > logs/engine.testnet.log 2>&1 & echo $! > runtime/testnet-engine.pid
sleep 2
nohup python -m uvicorn nexus_testnet_bridge:app --host 127.0.0.1 --port 8100 --workers 1 > logs/nexus_bridge.log 2>&1 & echo $! > runtime/testnet-bridge.pid
for i in $(seq 1 20); do curl -fsS "http://127.0.0.1:${TESTNET_PORT}/health" >/dev/null 2>&1 && break; sleep 1; done
curl -fsS "http://127.0.0.1:${TESTNET_PORT}/health"; echo
curl -fsS http://127.0.0.1:8100/health; echo
curl -fsS http://127.0.0.1:8100/status; echo
curl -fsS http://127.0.0.1:8100/testnet/time; echo
ss -ltn 2>/dev/null | grep -E ':(8000|8100)\b' || true
