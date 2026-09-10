#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail

ROOT="$HOME/honeycomb-execution-core"
cd "$ROOT"

ENGINE_PORT="${ENGINE_PORT:-8000}"
BRIDGE_PORT="${TESTNET_PORT:-8100}"
ENV="$ROOT/.env"
RUNTIME="$ROOT/runtime"

mkdir -p "$RUNTIME" "$ROOT/logs"

echo "=== HONEYCOMB TESTNET FULL REPAIR ==="
date

# ============================================================
# 1. BACKUP — NOTHING DELETED
# ============================================================
cp -f "$ENV" "$ENV.backup.$(date +%Y%m%d_%H%M%S)" 2>/dev/null || true

# ============================================================
# 2. REPAIR .env ASSIGNMENT SYNTAX
#    Fixes: KEY = value / KEY= value -> KEY=value
# ============================================================
python - <<'PY'
from pathlib import Path
import re

p = Path(".env")
lines = p.read_text().splitlines()
out = []

for line in lines:
    if re.match(r'^\s*[A-Za-z_][A-Za-z0-9_]*\s*=', line):
        line = re.sub(
            r'^(\s*[A-Za-z_][A-Za-z0-9_]*)\s*=\s*',
            r'\1=',
            line,
            count=1
        )
    out.append(line)

p.write_text("\n".join(out) + "\n")
print("ENV_SYNTAX_REPAIRED=PASS")
PY

# ============================================================
# 3. SAFE ENV LOAD
# ============================================================
set -a
. "$ENV"
set +a

: "${BINANCE_TESTNET_API_KEY:?BINANCE_TESTNET_API_KEY missing}"
: "${BINANCE_TESTNET_SECRET:?BINANCE_TESTNET_SECRET missing}"
: "${BINANCE_TESTNET_URL:?BINANCE_TESTNET_URL missing}"

echo "ENV_LOAD=PASS"
echo "API_KEY_LENGTH=${#BINANCE_TESTNET_API_KEY}"
echo "SECRET_LENGTH=${#BINANCE_TESTNET_SECRET}"
echo "TESTNET_URL=$BINANCE_TESTNET_URL"

# ============================================================
# 4. PUBLIC CONNECTIVITY
# ============================================================
python - <<'PY'
import os, requests, sys

base=os.environ["BINANCE_TESTNET_URL"].rstrip("/")

r=requests.get(
    base + "/fapi/v1/time",
    timeout=15
)

print("PUBLIC_HTTP_STATUS=", r.status_code)
print("PUBLIC_RESPONSE=", r.text[:200])

if r.status_code != 200:
    sys.exit(10)

r=requests.get(
    base + "/fapi/v1/exchangeInfo",
    timeout=15
)

print("EXCHANGEINFO_HTTP_STATUS=", r.status_code)

if r.status_code != 200:
    sys.exit(11)

data=r.json()
symbols={x["symbol"] for x in data.get("symbols",[])}

print("BTCUSDT_EXCHANGEINFO=", "PASS" if "BTCUSDT" in symbols else "FAIL")

if "BTCUSDT" not in symbols:
    sys.exit(12)
PY

# ============================================================
# 5. SIGNED ACCOUNT AUTH
# ============================================================
cat > "$RUNTIME/testnet_auth.py" <<'PY'
import os
import time
import hmac
import hashlib
import requests
import sys
from urllib.parse import urlencode

base=os.environ["BINANCE_TESTNET_URL"].rstrip("/")
key=os.environ["BINANCE_TESTNET_API_KEY"]
secret=os.environ["BINANCE_TESTNET_SECRET"]

params={
    "timestamp": int(time.time()*1000),
    "recvWindow": 10000,
}

query=urlencode(params)
signature=hmac.new(
    secret.encode(),
    query.encode(),
    hashlib.sha256
).hexdigest()

url=f"{base}/fapi/v2/account?{query}&signature={signature}"

r=requests.get(
    url,
    headers={"X-MBX-APIKEY":key},
    timeout=15
)

print("AUTH_HTTP_STATUS=", r.status_code)

try:
    d=r.json()
except Exception:
    print("AUTH_NON_JSON")
    print(r.text[:500])
    sys.exit(20)

if isinstance(d,dict) and d.get("code") == -2015:
    print("AUTH=FAIL_-2015")
    print("KEY_OR_SECRET_OR_PERMISSION=INVALID")
    sys.exit(2015)

if r.status_code != 200:
    print("AUTH=FAIL")
    print("RESPONSE=", d)
    sys.exit(21)

print("AUTH=PASS")
print("ACCOUNT_ASSET_COUNT=", len(d.get("assets",[])))
print("ACCOUNT_POSITION_COUNT=", len(d.get("positions",[])))

available=0.0

for a in d.get("assets",[]):
    if a.get("asset") == "USDT":
        available=float(a.get("availableBalance","0"))
        break

print("USDT_AVAILABLE=", available)
PY

chmod 700 "$RUNTIME/testnet_auth.py"

python "$RUNTIME/testnet_auth.py"

# ============================================================
# 6. ORDER FILTER DISCOVERY
# ============================================================
python - <<'PY'
import os, requests

base=os.environ["BINANCE_TESTNET_URL"].rstrip("/")

d=requests.get(
    base+"/fapi/v1/exchangeInfo",
    timeout=15
).json()

s=next(x for x in d["symbols"] if x["symbol"]=="BTCUSDT")

print("BTC_STATUS=",s.get("status"))
print("BTC_CONTRACT=",s.get("contractType"))

for f in s.get("filters",[]):
    if f.get("filterType") in ("LOT_SIZE","MARKET_LOT_SIZE","MIN_NOTIONAL","NOTIONAL"):
        print(
            "FILTER",
            f.get("filterType"),
            "minQty=",f.get("minQty"),
            "stepSize=",f.get("stepSize"),
            "minNotional=",f.get("notional")
        )
PY

# ============================================================
# 7. TESTNET ORDER ENGINE
#    0.001 BTC is intentionally small and testnet-only.
# ============================================================
cat > "$RUNTIME/testnet_live_order.py" <<'PY'
import os
import time
import hmac
import hashlib
import requests
import sys
from urllib.parse import urlencode

BASE=os.environ["BINANCE_TESTNET_URL"].rstrip("/")
KEY=os.environ["BINANCE_TESTNET_API_KEY"]
SECRET=os.environ["BINANCE_TESTNET_SECRET"]

SYMBOL="BTCUSDT"
QTY="0.001"

session=requests.Session()
session.headers.update({"X-MBX-APIKEY":KEY})

def signed(method,path,params=None):
    params=params or {}
    params["timestamp"]=int(time.time()*1000)
    params["recvWindow"]=10000

    query=urlencode(params)

    sig=hmac.new(
        SECRET.encode(),
        query.encode(),
        hashlib.sha256
    ).hexdigest()

    url=f"{BASE}{path}?{query}&signature={sig}"

    r=session.request(
        method,
        url,
        timeout=15
    )

    try:
        data=r.json()
    except Exception:
        print("NON_JSON=",r.text[:500])
        sys.exit(30)

    return r,data

# ------------------------------------------------------------
# ACCOUNT
# ------------------------------------------------------------
r,a=signed("GET","/fapi/v2/account")

print("ACCOUNT_STATUS=",r.status_code)

if r.status_code != 200:
    print("ACCOUNT_ERROR=",a)
    sys.exit(31)

# ------------------------------------------------------------
# POSITION MODE
# ------------------------------------------------------------
r,mode=signed("GET","/fapi/v1/positionSide/dual")

print("POSITION_MODE_STATUS=",r.status_code)

if r.status_code == 200:
    hedge=bool(mode.get("dualSidePosition"))
else:
    hedge=False

print("HEDGE_MODE=",hedge)

# ------------------------------------------------------------
# OPEN TESTNET MARKET POSITION
# ------------------------------------------------------------
open_params={
    "symbol":SYMBOL,
    "side":"BUY",
    "type":"MARKET",
    "quantity":QTY,
    "newOrderRespType":"RESULT",
}

if hedge:
    open_params["positionSide"]="LONG"

r,order=signed(
    "POST",
    "/fapi/v1/order",
    open_params
)

print("OPEN_ORDER_HTTP=",r.status_code)

if r.status_code != 200:
    print("OPEN_ORDER_ERROR=",order)
    sys.exit(32)

order_id=order.get("orderId")

print("TESTNET_ORDER=PASS")
print("ORDER_ID=",order_id)
print("ORDER_STATUS=",order.get("status"))
print("EXECUTED_QTY=",order.get("executedQty"))
print("AVG_PRICE=",order.get("avgPrice"))

if not order_id:
    sys.exit(33)

# ------------------------------------------------------------
# VERIFY ORDER
# ------------------------------------------------------------
time.sleep(1)

r,verify=signed(
    "GET",
    "/fapi/v1/order",
    {
        "symbol":SYMBOL,
        "orderId":order_id
    }
)

print("ORDER_VERIFY_HTTP=",r.status_code)

if r.status_code != 200:
    print("ORDER_VERIFY_ERROR=",verify)
    sys.exit(34)

print("ORDER_VERIFY_STATUS=",verify.get("status"))
print("ORDER_VERIFY_EXECUTED=",verify.get("executedQty"))

# ------------------------------------------------------------
# VERIFY POSITION
# ------------------------------------------------------------
r,pos=signed(
    "GET",
    "/fapi/v2/positionRisk",
    {"symbol":SYMBOL}
)

print("POSITION_VERIFY_HTTP=",r.status_code)

if r.status_code != 200:
    print("POSITION_VERIFY_ERROR=",pos)
    sys.exit(35)

active=[]

for p in pos:
    amt=float(p.get("positionAmt","0"))
    if abs(amt) > 0:
        active.append(p)

print("ACTIVE_POSITIONS=",len(active))

for p in active:
    print(
        "POSITION",
        p.get("symbol"),
        "side=",p.get("positionSide"),
        "amount=",p.get("positionAmt"),
        "entry=",p.get("entryPrice")
    )

if not active:
    print("POSITION_VERIFY=FAIL")
    sys.exit(36)

# ------------------------------------------------------------
# CLOSE POSITION
# ------------------------------------------------------------
close_params={
    "symbol":SYMBOL,
    "side":"SELL",
    "type":"MARKET",
    "quantity":QTY,
    "newOrderRespType":"RESULT",
}

if hedge:
    close_params["positionSide"]="LONG"
else:
    close_params["reduceOnly"]="true"

r,close=signed(
    "POST",
    "/fapi/v1/order",
    close_params
)

print("CLOSE_ORDER_HTTP=",r.status_code)

if r.status_code != 200:
    print("CLOSE_ORDER_ERROR=",close)
    sys.exit(37)

print("CLOSE_ORDER_ID=",close.get("orderId"))
print("CLOSE_ORDER_STATUS=",close.get("status"))
print("CLOSE_EXECUTED_QTY=",close.get("executedQty"))

# ------------------------------------------------------------
# FINAL POSITION CHECK
# ------------------------------------------------------------
time.sleep(1)

r,pos=signed(
    "GET",
    "/fapi/v2/positionRisk",
    {"symbol":SYMBOL}
)

if r.status_code != 200:
    print("FINAL_POSITION_CHECK=FAIL")
    sys.exit(38)

remaining=[]

for p in pos:
    if abs(float(p.get("positionAmt","0"))) > 0:
        remaining.append(p)

print("FINAL_ACTIVE_POSITIONS=",len(remaining))

if remaining:
    print("FINAL_FLAT=FAIL")
    for p in remaining:
        print(
            p.get("symbol"),
            p.get("positionSide"),
            p.get("positionAmt")
        )
    sys.exit(39)

print("FINAL_FLAT=PASS")
print("=== TESTNET LIVE ORDER CYCLE PASS ===")
PY

chmod 700 "$RUNTIME/testnet_live_order.py"

python "$RUNTIME/testnet_live_order.py"

# ============================================================
# 8. STOP ONLY OLD HONEYCOMB PROCESSES
# ============================================================
echo "=== STOP OLD HONEYCOMB PROCESSES ==="

pkill -f "$ROOT/engine.py" 2>/dev/null || true
pkill -f "$ROOT/engine_alpha.py" 2>/dev/null || true
pkill -f "$ROOT/engine_alpha2.py" 2>/dev/null || true
pkill -f "$ROOT/nexus_testnet_bridge.py" 2>/dev/null || true

sleep 2

# ============================================================
# 9. START ENGINE :8000
# ============================================================
echo "=== START ENGINE :8000 ==="

nohup python "$ROOT/engine.py" \
    > "$ROOT/logs/engine_testnet.log" 2>&1 &

ENGINE_PID=$!
echo "$ENGINE_PID" > "$RUNTIME/engine.pid"

sleep 3

# ============================================================
# 10. START BRIDGE :8100
# ============================================================
echo "=== START BRIDGE :8100 ==="

if [ -f "$ROOT/nexus_testnet_bridge.py" ]; then
    nohup python "$ROOT/nexus_testnet_bridge.py" \
        --host 127.0.0.1 \
        --port 8100 \
        > "$ROOT/logs/nexus_bridge.log" 2>&1 &

    BRIDGE_PID=$!
    echo "$BRIDGE_PID" > "$RUNTIME/bridge.pid"
fi

sleep 3

# ============================================================
# 11. SERVICE CHECK
# ============================================================
echo "=== SERVICE CHECK ==="

echo "--- PORT 8000 ---"
curl -sS --max-time 5 http://127.0.0.1:8000/health || true
echo

echo "--- PORT 8100 ---"
curl -sS --max-time 5 http://127.0.0.1:8100/health || \
curl -sS --max-time 5 http://127.0.0.1:8100/status || true
echo

echo "--- PROCESS ---"
ps -ef | grep -E 'engine.py|nexus_testnet_bridge.py' | grep -v grep || true

echo "--- LISTENING ---"
if command -v ss >/dev/null 2>&1; then
    ss -ltnp 2>/dev/null | grep -E ':8000|:8100' || true
else
    netstat -ltn 2>/dev/null | grep -E ':8000|:8100' || true
fi

echo "--- ENGINE LOG ---"
tail -n 30 "$ROOT/logs/engine_testnet.log" 2>/dev/null || true

echo "--- BRIDGE LOG ---"
tail -n 30 "$ROOT/logs/nexus_bridge.log" 2>/dev/null || true

echo
echo "=============================================="
echo "HONEYCOMB TESTNET REPAIR = COMPLETE"
echo "BINANCE TESTNET AUTH      = PASS"
echo "TESTNET ORDER CYCLE       = PASS"
echo "ORDER OPEN                = PASS"
echo "POSITION VERIFY           = PASS"
echo "ORDER CLOSE               = PASS"
echo "FINAL FLAT                = PASS"
echo "ENGINE                    = $ENGINE_PORT"
echo "BRIDGE                    = $BRIDGE_PORT"
echo "=============================================="
