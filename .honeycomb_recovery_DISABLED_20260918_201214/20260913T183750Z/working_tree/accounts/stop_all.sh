#!/data/data/com.termux/files/usr/bin/bash
cd "$(dirname "$0")"
for d in USDT-1 USDT-2 USDT-3 USDT-4 USDT-5 COIN-1 COIN-2 COIN-3 COIN-4 COIN-5; do
    if [ -f "pids/$d.pid" ]; then
        PID=$(cat "pids/$d.pid")
        if kill "$PID" 2>/dev/null; then
            echo "[$d] durduruldu (pid $PID)"
        fi
        rm -f "pids/$d.pid"
    fi
done
