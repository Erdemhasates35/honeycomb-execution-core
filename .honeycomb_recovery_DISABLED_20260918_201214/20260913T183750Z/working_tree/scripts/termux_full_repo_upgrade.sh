#!/data/data/com.termux/files/usr/bin/bash
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1

TS="$(date +%Y%m%d_%H%M%S)"
LOG="backups/termux_full_repair_${TS}.log"
mkdir -p backups

exec > >(tee "$LOG") 2>&1

echo "===== HONEYCOMB FULL REPAIR $TS ====="

export PYTHONPATH="$ROOT"
export EXECUTION_MODE=PAPER
export HONEYCOMB_MODE=PAPER
export LIVE_ARMED=0

echo "[1] Git state"
git status --short

echo "[2] Conflict forensic repair"
python3 scripts/repo_conflict_forensic_repair.py
RC=$?

if [ "$RC" -ne 0 ]; then
    echo "REPAIR_STOPPED RC=$RC"
    echo "LIVE ENGINE NOT STARTED"
    exit "$RC"
fi

echo "[3] Python compile"
python3 -m compileall -q \
    live \
    alpha_core.py \
    sovereign_parliament_engine.py \
    extreme_scanner_engine.py \
    extreme_scanner_omega.py \
    helix_sovereign_pro.py

RC=$?
if [ "$RC" -ne 0 ]; then
    echo "PYTHON_COMPILE_FAILED RC=$RC"
    exit "$RC"
fi

echo "[4] Final merge-marker scan"

if grep -RIn \
    --exclude-dir=.git \
    --exclude-dir=backups \
    --exclude-dir=__pycache__ \
    --exclude='*.bak*' \
    -E '^(<<<<<<<|=======|>>>>>>>)' \
    .; then

    echo "FATAL: unresolved merge markers remain"
    exit 21
fi

echo "MERGE_MARKERS=0"

echo "[5] LIVE GATE"
echo "EXECUTION_MODE=$EXECUTION_MODE"
echo "HONEYCOMB_MODE=$HONEYCOMB_MODE"
echo "LIVE_ARMED=$LIVE_ARMED"

echo
echo "===== REPAIR COMPLETE ====="
echo "No trading engine was started."
echo "No live order was created."

exit 0
