#!/data/data/com.termux/files/usr/bin/bash
set -u
cd /data/data/com.termux/files/home/honeycomb-execution-core
export PYTHONPATH="$PWD"
export EXECUTION_MODE=LIVE
export HONEYCOMB_MODE=LIVE
export LIVE_ARMED=1
exec python3 scripts/honeycomb_live_gate.py
