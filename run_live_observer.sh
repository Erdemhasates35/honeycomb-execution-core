#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
cd /data/data/com.termux/files/home/honeycomb-execution-core
export EXECUTION_MODE="${EXECUTION_MODE:-LIVE}"
export HONEYCOMB_MODE="${HONEYCOMB_MODE:-LIVE}"
exec python3 live/binance_user_stream.py
