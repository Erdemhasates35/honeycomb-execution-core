#!/data/data/com.termux/files/usr/bin/bash
set -u
cd /data/data/com.termux/files/home/honeycomb-execution-core || exit 1
export PYTHONPATH="$PWD"
python3 scripts/repo_integrity_profit_repair.py
printf '\n=== GIT CONFLICT MARKER CHECK ===\n'
if git grep -n -E '^(<<<<<<<|=======|>>>>>>>)' -- '*.py' '*.js' '*.mjs' '*.ts' '*.tsx' '*.sh' '*.json' '*.yml' '*.yaml' '*.toml' 2>/dev/null; then
  echo 'CONFLICT_MARKERS_REMAIN=YES'
else
  echo 'CONFLICT_MARKERS_REMAIN=NO'
fi
printf '\n=== HELIX SYNTAX ===\n'
python3 -m py_compile helix_sovereign_pro.py && echo 'HELIX_PYCOMPILE=OK' || echo 'HELIX_PYCOMPILE=FAIL'
printf '\n=== KERNEL SYNTAX ===\n'
python3 -m py_compile live/kernel.py && echo 'KERNEL_PYCOMPILE=OK' || echo 'KERNEL_PYCOMPILE=FAIL'
printf '\n=== GIT STATUS ===\n'
git status --short
