#!/data/data/com.termux/files/usr/bin/bash
cd "$(dirname "$0")"
mkdir -p logs pids
for d in USDT-1 USDT-2 USDT-3 USDT-4 USDT-5 COIN-1 COIN-2 COIN-3 COIN-4 COIN-5; do
    if [ -f "pids/$d.pid" ] && kill -0 "$(cat pids/$d.pid)" 2>/dev/null; then
        echo "[$d] zaten çalışıyor (pid $(cat pids/$d.pid))"
        continue
    fi
    (cd "$d" && nohup python3 sovereign_parliament_engine.py > "../logs/$d.log" 2>&1 & echo $! > "../pids/$d.pid")
    echo "[$d] başlatıldı (pid $(cat pids/$d.pid)) — log: accounts/logs/$d.log"
done
