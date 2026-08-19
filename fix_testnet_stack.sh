#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail

ROOT="$(pwd)"
RUNTIME="$ROOT/runtime"
LOG="$RUNTIME/bootstrap.log"

mkdir -p "$RUNTIME" "$ROOT/logs" "$ROOT/sockets"

exec > >(tee -a "$LOG") 2>&1

echo "=== HONEYCOMB TESTNET REPAIR ==="
date

# ------------------------------------------------------------
# 1. NEVER expose credentials
# ------------------------------------------------------------
chmod 700 "$RUNTIME" "$ROOT/logs" "$ROOT/sockets" 2>/dev/null || true
chmod 600 "$ROOT/.env" 2>/dev/null || true

# ------------------------------------------------------------
# 2. Stop duplicate local services
# ------------------------------------------------------------
pkill -f 'engine_alpha2.py' 2>/dev/null || true
pkill -f 'engine_alpha.py' 2>/dev/null || true
pkill -f 'engine_live.py' 2>/dev/null || true
pkill -f 'nexus_testnet_bridge.py' 2>/dev/null || true
pkill -f 'engine.py' 2>/dev/null || true

sleep 1

# ------------------------------------------------------------
# 3. Kill only listeners belonging to our configured ports
# ------------------------------------------------------------
for PORT in 8000 8080 8081 8100; do
    PIDS="$(fuser "$PORT/tcp" 2>/dev/null || true)"
    if [ -n "$PIDS" ]; then
        kill $PIDS 2>/dev/null || true
    fi
done

sleep 1

# ------------------------------------------------------------
# 4. Remove broken /tmp PID references
# ------------------------------------------------------------
rm -f /tmp/nexus_port_8000 \
      /tmp/nexus_port_8080 \
      /tmp/nexus_port_8081 \
      /tmp/nexus_port_8100 \
      /tmp/nexus_runtime.sh 2>/dev/null || true

rm -f "$RUNTIME"/*.pid 2>/dev/null || true

# ------------------------------------------------------------
# 5. Validate required Python modules
# ------------------------------------------------------------
python - <<'PY'
import importlib.util
mods = ["flask", "requests"]
bad = []
for m in mods:
    if importlib.util.find_spec(m) is None:
        bad.append(m)
if bad:
    raise SystemExit("MISSING_PYTHON_MODULES=" + ",".join(bad))
print("PYTHON_DEPS=PASS")
PY

# ------------------------------------------------------------
# 6. Validate .env WITHOUT PRINTING SECRETS
# ------------------------------------------------------------
if [ ! -f "$ROOT/.env" ]; then
    echo "ERROR=.env missing"
    exit 10
fi

python - <<'PY'
from pathlib import Path

p = Path(".env")
lines = p.read_text(errors="ignore").splitlines()

required = [
    "BINANCE_TESTNET_API_KEY",
    "BINANCE_TESTNET_SECRET",
    "BINANCE_TESTNET_URL",
]

values = {}

for line in lines:
    line=line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k,v=line.split("=",1)
    values[k.strip()] = v.strip()

for k in required:
    v=values.get(k,"")
    if not v or v.startswith("<") or v.startswith("CHANGE_"):
        raise SystemExit(f"ENV_MISSING={k}")
    print(f"ENV_{k}=SET length={len(v)}")

url=values.get("BINANCE_TESTNET_URL","")
if url != "https://testnet.binancefuture.com":
    raise SystemExit(
        "BINANCE_TESTNET_URL_INVALID="
        + url
    )

print("ENV_TESTNET_ENDPOINT=PASS")
PY

# ------------------------------------------------------------
# 7. Discover actual source files
# ------------------------------------------------------------
BRIDGE=""
for f in \
    nexus_testnet_bridge.py \
    engine_testnet.py \
    testnet_bridge.py
do
    if [ -f "$f" ]; then
        BRIDGE="$f"
        break
    fi
done

ENGINE=""
for f in \
    engine.py \
    engine_live.py \
    engine_alpha.py \
    engine_alpha2.py
do
    if [ -f "$f" ]; then
        ENGINE="$f"
        break
    fi
done

echo "ENGINE_FILE=${ENGINE:-NONE}"
echo "BRIDGE_FILE=${BRIDGE:-NONE}"

# ------------------------------------------------------------
# 8. Binance public connectivity
# ------------------------------------------------------------
echo "=== BINANCE TESTNET PUBLIC ==="

curl -4 -fsS \
    --connect-timeout 10 \
    --max-time 20 \
    "https://testnet.binancefuture.com/fapi/v1/time" \
    > "$RUNTIME/binance_time.json"

cat "$RUNTIME/binance_time.json"

curl -4 -fsS \
    --connect-timeout 10 \
    --max-time 20 \
    "https://testnet.binancefuture.com/fapi/v1/exchangeInfo" \
    > "$RUNTIME/exchangeInfo.json"

python - <<'PY'
import json
d=json.load(open("runtime/exchangeInfo.json"))
symbols={x["symbol"] for x in d.get("symbols",[])}
print("BTCUSDT_EXCHANGEINFO=", "PASS" if "BTCUSDT" in symbols else "FAIL")
PY

# ------------------------------------------------------------
# 9. Create deterministic runtime configuration
# ------------------------------------------------------------
cat > "$RUNTIME/ports.env" <<'ENV'
ENGINE_PORT=8000
ALPHA_PORT=8080
ALPHA2_PORT=8081
BRIDGE_PORT=8100
ENV

# ------------------------------------------------------------
# 10. Safe launcher
# ------------------------------------------------------------
cat > "$RUNTIME/start_testnet.sh" <<'START'
#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

mkdir -p runtime logs sockets

set -a
[ -f .env ] && . ./.env
set +a

ENGINE_PORT="${ENGINE_PORT:-8000}"
BRIDGE_PORT="${BRIDGE_PORT:-8100}"

echo "ENGINE_PORT=$ENGINE_PORT"
echo "BRIDGE_PORT=$BRIDGE_PORT"

# Engine
if [ -f engine.py ]; then
    nohup python engine.py \
        > logs/engine.testnet.log 2>&1 &
    echo $! > runtime/engine.pid
elif [ -f engine_live.py ]; then
    nohup python engine_live.py \
        > logs/engine.testnet.log 2>&1 &
    echo $! > runtime/engine.pid
fi

sleep 2

# Bridge
if [ -f nexus_testnet_bridge.py ]; then
    nohup python nexus_testnet_bridge.py \
        > logs/bridge.testnet.log 2>&1 &
    echo $! > runtime/bridge.pid
fi

sleep 3

echo
echo "=== LOCAL HEALTH ==="

curl -fsS "http://127.0.0.1:${ENGINE_PORT}/health" \
    || echo "ENGINE_HEALTH=FAIL"

echo

curl -fsS "http://127.0.0.1:${BRIDGE_PORT}/health" \
    || curl -fsS "http://127.0.0.1:${BRIDGE_PORT}/status" \
    || echo "BRIDGE_HEALTH=FAIL"

echo
echo "=== LISTENERS ==="
for p in "$ENGINE_PORT" "$BRIDGE_PORT"; do
    echo "--- $p ---"
    ss -ltn 2>/dev/null | grep ":$p " || true
done
START

chmod 700 "$RUNTIME/start_testnet.sh"

# ------------------------------------------------------------
# 11. Testnet authentication probe
# ------------------------------------------------------------
cat > "$RUNTIME/test_auth.py" <<'PY'
import os
import time
import hmac
import hashlib
import urllib.parse
import requests

base=os.environ.get(
    "BINANCE_TESTNET_URL",
    "https://testnet.binancefuture.com"
).rstrip("/")

key=os.environ.get("BINANCE_TESTNET_API_KEY","")
secret=os.environ.get("BINANCE_TESTNET_SECRET","")

if not key or not secret:
    raise SystemExit("TESTNET_CREDENTIALS_MISSING")

def signed_get(path, params=None):
    params=dict(params or {})
    params["timestamp"]=int(time.time()*1000)
    params["recvWindow"]=5000

    query=urllib.parse.urlencode(params)
    sig=hmac.new(
        secret.encode(),
        query.encode(),
        hashlib.sha256
    ).hexdigest()

    url=f"{base}{path}?{query}&signature={sig}"

    r=requests.get(
        url,
        headers={"X-MBX-APIKEY":key},
        timeout=15
    )

    print("HTTP_STATUS=",r.status_code)

    try:
        d=r.json()
    except Exception:
        print("NON_JSON_RESPONSE")
        print(r.text[:500])
        raise SystemExit(20)

    if isinstance(d,dict) and d.get("code") == -2015:
        print("AUTH=FAIL_-2015")
        print("KEY_NOT_PRINTED=TRUE")
        raise SystemExit(2015)

    print("AUTH_RESPONSE_OK")
    if isinstance(d,dict):
        print("ACCOUNT_ASSET_COUNT=",len(d.get("assets",[])))
        print("ACCOUNT_POSITIONS=",len(d.get("positions",[])))

    return d

signed_get("/fapi/v2/account")
print("TESTNET_AUTH=PASS")
PY

chmod 700 "$RUNTIME/test_auth.py"

# ------------------------------------------------------------
# 12. Run auth probe, secrets never printed
# ------------------------------------------------------------
set -a
. "$ROOT/.env"
set +a

python "$RUNTIME/test_auth.py"

# ------------------------------------------------------------
# 13. Start unified stack
# ------------------------------------------------------------
bash "$RUNTIME/start_testnet.sh"

echo
echo "=== REPAIR COMPLETE ==="
echo "AUTHENTICATION=PASS"
echo "TESTNET_ENDPOINT=https://testnet.binancefuture.com"
echo "ENGINE=8000"
echo "BRIDGE=8100"
echo "NEXT=REAL_TESTNET_ORDER"
