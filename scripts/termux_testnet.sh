#!/data/data/com.termux/files/usr/bin/bash
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

: "${TRADING_ENV:=testnet}"
if [ "$TRADING_ENV" != "testnet" ]; then
  echo "ERROR: TRADING_ENV must be testnet"
  exit 1
fi

mkdir -p "$HOME/.honeycomb" reports results
export HONEYCOMB_LOCK_PATH="${HONEYCOMB_LOCK_PATH:-$HOME/.honeycomb/sf.lock}"

echo "[1] Python syntax"
python -m py_compile engine_testnet.py

echo "[2] Non-destructive DB/source audit"
python scripts/honeycomb_integrity_audit.py

echo "[3] Go"
if command -v go >/dev/null 2>&1 && [ -f go.mod ]; then
  go test ./...
  go vet ./...
  go build ./...
fi

echo "[4] Honeycomb AL"
AL="${HONEYCOMB_AL_PATH:-../honeycomb_al}"
if [ -d "$AL" ] && [ -f "$AL/package.json" ]; then
  (cd "$AL" && npm test)
  (cd "$AL" && npm run typecheck)
  (cd "$AL" && npm run build)
fi

echo "[5] Testnet engine"
python engine_testnet.py
