#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
cd /data/data/com.termux/files/home/honeycomb-execution-core
TS="$(date +%Y%m%d_%H%M%S)"
mkdir -p .honeycomb_runtime "backups/termux_hardening_$TS"
for f in honeycomb_execution_guard.py sitecustomize.py sovereign_parliament_engine.py tests/test_execution_guard.py tests/test_parliament_contract.py; do
  if [ -e "$f" ]; then cp -a "$f" "backups/termux_hardening_$TS/$(basename "$f").bak"; fi
done

git fetch origin main
git show origin/main:honeycomb_execution_guard.py > honeycomb_execution_guard.py
git show origin/main:sitecustomize.py > sitecustomize.py
git show origin/main:sovereign_parliament_engine.py > sovereign_parliament_engine.py
mkdir -p tests
git show origin/main:tests/test_execution_guard.py > tests/test_execution_guard.py
git show origin/main:tests/test_parliament_contract.py > tests/test_parliament_contract.py

python3 -m py_compile honeycomb_execution_guard.py sitecustomize.py sovereign_parliament_engine.py live/kernel.py engine_alpha2.py
python3 -m pytest -q tests/test_execution_guard.py tests/test_parliament_contract.py

python3 - <<'PY'
import os
for k in ("EXECUTION_MODE","HONEYCOMB_MODE","LIVE_ARMED"):
    print(k, "=", os.getenv(k, ""))
print("LEARNING_DB_PATH=", os.getenv("LEARNING_DB_PATH", ""))
PY

echo "HARDENING INSTALLED; backup=backups/termux_hardening_$TS"
echo "Next: wait for any active Binance 418 ban to expire; then run the signed diagnostics before enabling LIVE order tests."
