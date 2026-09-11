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
python3 -m py_compile live/protection_bridge.py profit_economics.py aggressive_profit_optimizer.py profit_max_engine.py aggressive_live_engine.py lobster_extreme_momentum_engine.py live/maker_sniper.py
printf '%s\n' '[PROFIT-MAX] COMPILE_OK min_leverage=40 max_leverage='"$MAX_LEVERAGE"' style='"$EXECUTION_STYLE"
exec python3 profit_max_engine.py
