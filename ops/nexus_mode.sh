#!/bin/sh
# Her yerden çalışır. Klasör yoksa klonlar. Sır yok.
MODE=${1:-testnet}
ROOT="$HOME/honeycomb/honeycomb-execution-core"
mkdir -p "$HOME/honeycomb" "$HOME/.honeycomb"
if [ ! -d "$ROOT/.git" ]; then
  git clone --depth 1 https://github.com/Erdemhasates35/honeycomb-execution-core.git "$ROOT" || exit 1
fi
cd "$ROOT" || exit 1
git pull --ff-only || true
export HONEYCOMB_LOCK_PATH="$HOME/.honeycomb/sf.lock"
if [ "$MODE" = "live" ]; then
  export EXECUTION_MODE=LIVE
  export HONEYCOMB_MODE=LIVE
  export LIVE_ARMED=1
else
  export EXECUTION_MODE=TESTNET
  export HONEYCOMB_MODE=TESTNET
  export LIVE_ARMED=0
fi
exec python3 helix_sovereign_pro.py
