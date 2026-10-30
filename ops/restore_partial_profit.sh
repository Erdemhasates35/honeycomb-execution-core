#!/bin/sh
# Iki klon da olabilir. Sinif yoksa HEAD, o da yoksa origin/main.
for d in "$HOME/honeycomb-execution-core" "$HOME/honeycomb/honeycomb-execution-core"; do
  [ -f "$d/live/kernel.py" ] || continue
  echo "== $d"
  if grep -q "class PartialProfitEngine" "$d/live/kernel.py"; then
    echo "VAR"
    continue
  fi
  cp "$d/live/kernel.py" "$d/live/kernel.py.phone.bak"
  git -C "$d" checkout -- live/kernel.py 2>/dev/null || true
  if ! grep -q "class PartialProfitEngine" "$d/live/kernel.py"; then
    git -C "$d" fetch origin 2>/dev/null || true
    git -C "$d" checkout origin/main -- live/kernel.py || exit 1
  fi
  echo "ONAR yedek=$d/live/kernel.py.phone.bak"
done
cd "$HOME/honeycomb/honeycomb-execution-core" 2>/dev/null || cd "$HOME/honeycomb-execution-core" || exit 1
python3 -c "from live.kernel import PartialProfitEngine, LiveKernel; print('import OK', PartialProfitEngine.__name__)"
