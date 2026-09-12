#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
cd /data/data/com.termux/files/home/honeycomb-execution-core
export EXECUTION_MODE=LIVE
export HONEYCOMB_MODE=LIVE
export LIVE_ARMED=1
export MIN_LEVERAGE="${MIN_LEVERAGE:-40}"
export LEV_MIN="${LEV_MIN:-40}"
export MAX_LEVERAGE="${MAX_LEVERAGE:-75}"
export EXECUTION_STYLE="${EXECUTION_STYLE:-AUTO}"
exec python3 aggressive_live_engine.py
