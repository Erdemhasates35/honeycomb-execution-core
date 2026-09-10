#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
cd /data/data/com.termux/files/home/honeycomb-execution-core
export EXECUTION_MODE=LIVE
export HONEYCOMB_MODE=LIVE
export LIVE_ARMED=1
export LEV_MIN=50
export MAX_LEVERAGE=75
export LOBSTER_MAX_POSITIONS="${LOBSTER_MAX_POSITIONS:-3}"
exec python3 lobster_extreme_momentum_engine.py
