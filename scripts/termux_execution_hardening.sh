#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
cd /data/data/com.termux/files/home/honeycomb-execution-core
TS="$(date +%Y%m%d_%H%M%S)"
BACKUP="backups/termux_hardening_$TS"
mkdir -p .honeycomb_runtime "$BACKUP" tests

TARGETS=(
  honeycomb_execution_guard.py sitecustomize.py sovereign_parliament_engine.py
  honeycomb_node_guard.mjs package.json tsconfig.json verify.ts run_nexus_testnet.sh
  tests/test_execution_guard.py tests/test_parliament_contract.py
)
for f in "${TARGETS[@]}"; do
  if [ -e "$f" ]; then
    mkdir -p "$BACKUP/$(dirname "$f")"
    cp -a "$f" "$BACKUP/$f.bak"
  fi
done

git fetch origin main
for f in "${TARGETS[@]}"; do
  git show "origin/main:$f" > "$f"
done

python3 -m py_compile honeycomb_execution_guard.py sitecustomize.py sovereign_parliament_engine.py live/kernel.py engine_alpha2.py
python3 -m pytest -q tests/test_execution_guard.py tests/test_parliament_contract.py
node --check honeycomb_node_guard.mjs
npm run typecheck
npm test

python3 - <<'PY'
import os
for k in ("EXECUTION_MODE","HONEYCOMB_MODE","LIVE_ARMED"):
    print(k, "=", os.getenv(k, ""))
print("LEARNING_DB_PATH=", os.getenv("LEARNING_DB_PATH", ""))
PY

echo "HARDENING INSTALLED; backup=$BACKUP"
echo "No database file was deleted. Existing target files were backed up before sync."
echo "Next: run the signed time/balance/position diagnostics; do not place a LIVE order until they pass."
