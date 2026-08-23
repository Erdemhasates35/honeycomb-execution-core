#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
mkdir -p logs runtime
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
export HONEYCOMB_CONTROL_URL="${HONEYCOMB_CONTROL_URL:-http://127.0.0.1:8787}"
export HONEYCOMB_BRIDGE_URL="${HONEYCOMB_BRIDGE_URL:-http://127.0.0.1:8100}"
export HONEYCOMB_ENGINE_URL="${HONEYCOMB_ENGINE_URL:-http://127.0.0.1:8000}"
export UI_CONTROL_HOST="${UI_CONTROL_HOST:-127.0.0.1}"
export UI_CONTROL_PORT="${UI_CONTROL_PORT:-8788}"
if ! curl -fsS "${HONEYCOMB_CONTROL_URL}/api/status" >/dev/null 2>&1; then
  nohup python -m orchestrator.control_plane > logs/control_plane.log 2>&1 & echo $! > runtime/control_plane.pid
  sleep 1
fi
if [ -f runtime/ui_control_plane.pid ] && kill -0 "$(cat runtime/ui_control_plane.pid)" 2>/dev/null; then kill "$(cat runtime/ui_control_plane.pid)" 2>/dev/null || true; fi
nohup python -m orchestrator.ui_control_plane > logs/ui_control_plane.log 2>&1 & echo $! > runtime/ui_control_plane.pid
for i in $(seq 1 20); do curl -fsS "http://127.0.0.1:${UI_CONTROL_PORT}/api/ui/capabilities" >/dev/null 2>&1 && break; sleep 1; done
printf '\nHONEYCOMB UI GATEWAY: http://127.0.0.1:%s\n' "$UI_CONTROL_PORT"
curl -fsS "http://127.0.0.1:${UI_CONTROL_PORT}/api/ui/capabilities"; printf '\n'
curl -fsS "http://127.0.0.1:${UI_CONTROL_PORT}/api/ui/status"; printf '\n'
