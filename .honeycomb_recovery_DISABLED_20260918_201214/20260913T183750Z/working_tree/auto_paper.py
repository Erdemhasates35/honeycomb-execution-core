#!/data/data/com.termux/files/usr/bin/python3
import os, time, json, urllib.request, urllib.error
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except Exception:
    pass

BASE = "http://127.0.0.1:8080"
TARGET_PROFIT = float(os.getenv("TARGET_PROFIT_PERCENT", "25"))
MAX_LOSS = float(os.getenv("MAX_LOSS_PERCENT", "50"))
INTERVAL = int(os.getenv("AUTO_INTERVAL_SEC", "20"))
SYMBOLS = ["BTCUSDT", "ETHUSDT"]
SIZE = 0.01
LEVERAGE = 3
MAKER_FEE = 0.02

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

def http_json(method, path, body=None, timeout=8):
    url = BASE + path
    data = None
    headers = {"Connection": "close", "User-Agent": "honeycomb-auto/1"}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())

def safe(method, path, body=None):
    try:
        return http_json(method, path, body)
    except Exception as e:
        log(f"warn {method} {path}: {type(e).__name__}")
        return None

def main():
    log(f"AUTO PAPER | profit={TARGET_PROFIT}% loss={MAX_LOSS}% interval={INTERVAL}s")
    log("PAPER only | Binance sim | maker fee assumption")
    i = 0
    while True:
        st = safe("GET", "/status")
        if st:
            log(f"engine mode={st.get('mode')} risk={st.get('risk_state')} open={st.get('positions')}")
        else:
            log("engine unreachable — waiting")
            time.sleep(INTERVAL)
            continue

        symbol = SYMBOLS[i % len(SYMBOLS)]
        side = "LONG" if i % 2 == 0 else "SHORT"
        i += 1

        net = TARGET_PROFIT - (MAKER_FEE * 2)
        open_res = safe("POST", "/order/open", {
            "symbol": symbol,
            "side": side,
            "size": SIZE,
            "leverage": LEVERAGE,
            "exchange": "binance",
        })
        log(f"OPEN {side} {symbol} -> {open_res}")

        if not open_res or not open_res.get("success"):
            time.sleep(INTERVAL)
            continue

        time.sleep(5)

        close_res = safe("POST", "/order/close", {"symbol": symbol})
        log(f"CLOSE {symbol} -> {close_res} | paper_net≈{net:.2f}%")
        log(f"rules target={TARGET_PROFIT}% max_loss={MAX_LOSS}%")

        time.sleep(INTERVAL)

if __name__ == "__main__":
    main()
