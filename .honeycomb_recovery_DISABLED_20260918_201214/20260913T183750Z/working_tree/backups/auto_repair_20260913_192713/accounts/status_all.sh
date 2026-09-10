#!/data/data/com.termux/files/usr/bin/bash
cd "$(dirname "$0")"
PORT=8101
for d in USDT-1 USDT-2 USDT-3 USDT-4 USDT-5 COIN-1 COIN-2 COIN-3 COIN-4 COIN-5; do
    RUNNING="KAPALI"
    if [ -f "pids/$d.pid" ] && kill -0 "$(cat pids/$d.pid)" 2>/dev/null; then RUNNING="ÇALIŞIYOR"; fi
    echo "[$d] $RUNNING  panel: http://127.0.0.1:$PORT/"
    PORT=$((PORT + 1))
done
