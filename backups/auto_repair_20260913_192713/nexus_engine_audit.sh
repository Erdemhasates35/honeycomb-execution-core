#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail

ROOT="$HOME/honeycomb-execution-core"
OUT="$ROOT/runtime/sync/engine-audit.txt"

mkdir -p "$(dirname "$OUT")"
cd "$ROOT"

{
echo "================================================"
echo "QUANTUM NEXUS / HONEYCOMB ENGINE AUDIT"
echo "================================================"
date

echo
echo "=== PYTHON ENGINES ==="
find . -type f -name '*.py' \
 ! -path './.git/*' \
 ! -path './runtime/*' \
 ! -path './logs/*' \
 ! -path './.venv/*' \
 ! -path './venv/*' \
 | grep -Ei \
 'engine|alpha|nexus|honeycomb|arbitrage|execution|bridge|strategy|risk|brain|agent|orchestrator|market|binance' \
 || true

echo
echo "=== ENTRYPOINT CANDIDATES ==="

find . -type f \
 \( -name '*.py' -o -name '*.js' -o -name '*.ts' -o -name '*.sh' \) \
 ! -path './.git/*' \
 ! -path './runtime/*' \
 ! -path './logs/*' \
 ! -path './node_modules/*' \
 -print0 |
while IFS= read -r -d '' f; do

    if grep -qE \
        'if __name__ *== *["'\'']__main__["'\'']|app\.run|uvicorn|FastAPI|Flask|WebSocket|websocket|asyncio\.run|#!/' \
        "$f" 2>/dev/null; then

        echo "$f"
    fi
done

echo
echo "=== PORT DEFINITIONS ==="

grep -RniE \
 'PORT[[:space:]]*=|port[[:space:]]*=|:8000|:8080|:8081|:8100|:8200|listen\(' \
 . \
 --include='*.py' \
 --include='*.js' \
 --include='*.ts' \
 --include='*.json' \
 --include='*.yaml' \
 --include='*.yml' \
 --exclude-dir=.git \
 --exclude-dir=runtime \
 --exclude-dir=logs \
 --exclude-dir=node_modules \
 2>/dev/null | head -500 || true

echo
echo "=== EXCHANGE ADAPTERS ==="

grep -RniE \
 'binance|jupiter|bitget|bybit|okx|coinbase|websocket|fstream|ws-fapi|testnet|demo-fstream' \
 . \
 --include='*.py' \
 --include='*.js' \
 --include='*.ts' \
 --include='*.go' \
 --exclude-dir=.git \
 --exclude-dir=runtime \
 --exclude-dir=logs \
 --exclude-dir=node_modules \
 2>/dev/null | head -500 || true

echo
echo "=== STRATEGY / INDICATOR MODULES ==="

grep -RniE \
 'EMA|RSI|MACD|ATR|VWAP|ADX|BOLL|OBV|funding|openInterest|volatility|momentum|signal|strategy' \
 . \
 --include='*.py' \
 --include='*.js' \
 --include='*.ts' \
 --include='*.go' \
 --exclude-dir=.git \
 --exclude-dir=runtime \
 --exclude-dir=logs \
 --exclude-dir=node_modules \
 2>/dev/null | head -500 || true

echo
echo "=== RISK / EXECUTION ==="

grep -RniE \
 'authorizeOrder|risk|drawdown|leverage|max.*loss|max.*position|order|execution|reduceOnly|positionSide|clientOrderId' \
 . \
 --include='*.py' \
 --include='*.js' \
 --include='*.ts' \
 --include='*.go' \
 --exclude-dir=.git \
 --exclude-dir=runtime \
 --exclude-dir=logs \
 --exclude-dir=node_modules \
 2>/dev/null | head -500 || true

echo
echo "=== FRONTEND ==="

find . -maxdepth 3 -type f \
 \( -name 'package.json' -o -name 'vite.config.*' -o -name 'next.config.*' \
 -o -name 'app.json' -o -name 'app.config.*' \) \
 ! -path './node_modules/*' \
 ! -path './.git/*' \
 -print

echo
echo "=== SERVICES CURRENTLY ALIVE ==="

ps -ef 2>/dev/null | grep -E \
 'python|uvicorn|gunicorn|node|npm|go|engine|nexus|honeycomb' \
 | grep -v grep || true

echo
echo "=== END ==="

} | tee "$OUT"

echo
echo "AUDIT_FILE=$OUT"
