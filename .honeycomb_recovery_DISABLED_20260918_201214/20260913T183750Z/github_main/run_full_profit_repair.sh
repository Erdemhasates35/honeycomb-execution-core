#!/data/data/com.termux/files/usr/bin/bash
set -u
cd /data/data/com.termux/files/home/honeycomb-execution-core || exit 1
export PYTHONPATH="$PWD"
export EXECUTION_MODE=LIVE
export HONEYCOMB_MODE=LIVE
export LIVE_ARMED=1
export MIN_LEVERAGE="${MIN_LEVERAGE:-40}"
export LEV_MIN="${LEV_MIN:-40}"
export MAX_LEVERAGE="${MAX_LEVERAGE:-75}"
export EXECUTION_STYLE="${EXECUTION_STYLE:-AUTO}"

printf '%s\n' '=== HONEYCOMB FULL REPAIR / PROFIT GATE ==='
python3 scripts/repo_integrity_profit_repair.py || exit 2
printf '%s\n' '=== POST-REPAIR CONFLICT CHECK ==='
if git grep -n -E '^(<<<<<<<|=======|>>>>>>>)' -- '*.py' '*.js' '*.mjs' '*.ts' '*.tsx' '*.sh' '*.json' '*.yml' '*.yaml' '*.toml' 2>/dev/null; then
  echo 'CONFLICT_MARKERS_REMAIN=YES'
else
  echo 'CONFLICT_MARKERS_REMAIN=NO'
fi
printf '%s\n' '=== KEY PYTHON COMPILE ==='
python3 -m py_compile helix_sovereign_pro.py live/kernel.py live/protection_bridge.py profit_economics.py profit_max_engine.py aggressive_live_engine.py lobster_extreme_momentum_engine.py live/maker_sniper.py || exit 3
printf '%s\n' 'KEY_COMPILE=OK'
printf '%s\n' '=== LIVE ACCOUNT GATE / NO NEW ORDER ==='
exec bash ./run_live_gate.sh
