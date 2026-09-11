#!/data/data/com.termux/files/usr/bin/bash
set -u
cd /data/data/com.termux/files/home/honeycomb-execution-core
export PYTHONPATH="$PWD"
export EXECUTION_MODE=LIVE
export HONEYCOMB_MODE=LIVE
export LIVE_ARMED=1
export MIN_LEVERAGE="${MIN_LEVERAGE:-40}"
export MAX_LEVERAGE="${MAX_LEVERAGE:-75}"
export EXECUTION_STYLE="${EXECUTION_STYLE:-AUTO}"
exec python3 profit_max_engine.py
