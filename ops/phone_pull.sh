#!/bin/sh
# Iki klonu da ceker. Yerel kernel cakisirsa kenara alinir, origin kalir.
for d in "$HOME/honeycomb-execution-core" "$HOME/honeycomb/honeycomb-execution-core"; do
  [ -d "$d/.git" ] || continue
  echo "== $d"
  git -C "$d" pull --ff-only && continue
  git -C "$d" stash push -m "phone-kernel" -- live/kernel.py live/__init__.py || true
  git -C "$d" pull --ff-only || echo "CEKILEMEDI $d"
done
ROOT="$HOME/honeycomb/honeycomb-execution-core"
[ -d "$ROOT" ] || ROOT="$HOME/honeycomb-execution-core"
cd "$ROOT" || exit 1
python3 -c "from live.kernel import LiveKernel; from live.partial_profit import PartialProfitEngine; print('import OK')"
