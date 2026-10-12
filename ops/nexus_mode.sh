#!/bin/sh
# Mod seçer. Anahtarlar .env içinde kalır. Bu dosyada sır yoktur.
MODE=${1:-testnet}
ROOT="$HOME/honeycomb/honeycomb-execution-core"
if [ ! -d "$ROOT" ]; then
  mkdir -p "$HOME/honeycomb"
  git clone --depth 1 https://github.com/Erdemhasates35/honeycomb-execution-core.git "$ROOT" || exit 1
fi
cd "$ROOT" || exit 1
mkdir -p "$HOME/.honeycomb"
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
