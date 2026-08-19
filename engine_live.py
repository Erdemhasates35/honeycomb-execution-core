#!/data/data/com.termux/files/usr/bin/python3
# -*- coding: utf-8 -*-
import time, threading, json, urllib.request, urllib.parse, urllib.error, hmac, hashlib, os, sys, locale
from flask import Flask, jsonify

# Force UTF-8
os.environ["PYTHONIOENCODING"] = "utf-8"
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

def load_env(path):
    env = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip().split("#")[0].strip()
    return env

ENV = load_env(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

API_KEY = ENV.get("BINANCE_API_KEY") or os.getenv("BINANCE_API_KEY")
API_SEC = ENV.get("BINANCE_SECRET") or os.getenv("BINANCE_SECRET") or os.getenv("BINANCE_API_SECRET")
if not API_KEY or not API_SEC:
    print("KRITIK: BINANCE_API_KEY / BINANCE_SECRET eksik")
    sys.exit(1)

app = Flask(__name__)
PORT = int(ENV.get("LIVE_PORT", "8082"))
BASE_URL = ENV.get("BINANCE_FUTURES_URL", "https://fapi.binance.com")

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
FALLBACK = {"BTCUSDT": 64000.0, "ETHUSDT": 1870.0, "SOLUSDT": 76.0, "BNBUSDT": 600.0}
QTY_PREC = {"BTCUSDT": 3, "ETHUSDT": 3, "SOLUSDT": 2, "BNBUSDT": 2}
last_px = dict(FALLBACK)

RISK = float(ENV.get("LIVE_RISK", "0.18"))
LEV = float(ENV.get("MAX_LEVERAGE", "75"))
TP_M = float(ENV.get("TP_M", "16.0"))
FEE = float(ENV.get("FEE_RATE", "0.0004"))
TP_P = TP_M / LEV
SL_P = float(ENV.get("SL_P", "0.55"))
HOLD_MAX = int(ENV.get("HOLD_MAX", "10"))
INTERVAL = int(ENV.get("AUTO_INTERVAL_SEC", "4"))
COOLDOWN = int(ENV.get("COOLDOWN", "1"))
MAX_POS_USDT = float(ENV.get("MAX_POSITION_SIZE_USDT", "350"))
CB_THRESHOLD = int(ENV.get("CIRCUIT_BREAKER_THRESHOLD", "3"))
CB_COOLDOWN = int(ENV.get("CIRCUIT_BREAKER_COOLDOWN_SEC", "15"))
MIN_MARGIN = 0.6

balance = 10.0
peak = 10.0
positions, journal, logs = {}, [], []
lock = threading.RLock()
state = {"i": 0, "last": time.time()}
cb_state = {"fails": 0, "locked_until": 0.0}
hedge_mode = False

def safe(s):
    return str(s).encode("ascii", "replace").decode("ascii")

def log(msg):
    line = time.strftime("%H:%M:%S") + " [LIVE] " + safe(msg)
    with lock:
        logs.insert(0, line)
        if len(logs) > 300:
            logs.pop()
    print(line, flush=True)

def binance_request(method, endpoint, params=None, signed=True):
    if params is None:
        params = {}
    if signed:
        params["timestamp"] = int(time.time() * 1000)
        params["recvWindow"] = 5000
        query = urllib.parse.urlencode(params)
        sig = hmac.new(API_SEC.encode(), query.encode(), hashlib.sha256).hexdigest()
        payload = query + "&signature=" + sig
    else:
        payload = urllib.parse.urlencode(params) if params else ""
    headers = {
        "X-MBX-APIKEY": API_KEY,
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "hc-live"
    }
    if method == "GET":
        url = BASE_URL + endpoint + ("?" + payload if payload else "")
        req = urllib.request.Request(url, headers=headers)
    else:
        url = BASE_URL + endpoint
        req = urllib.request.Request(url, data=payload.encode(), headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.loads(r.read().decode("utf-8"))

def get_balance_usdt():
    try:
        res = binance_request("GET", "/fapi/v2/balance")
        for a in res:
            if a.get("asset") == "USDT":
                return float(a.get("balance", 0))
    except Exception as e:
        log("BALANCE ERR: %s" % e)
    return 0.0

def get_position_mode():
    try:
        res = binance_request("GET", "/fapi/v1/positionSide/dual")
        return bool(res.get("dualSidePosition", False))
    except Exception:
        return False

def get_position_amt(symbol, side):
    try:
        res = binance_request("GET", "/fapi/v2/positionRisk", {"symbol": symbol})
        for p in res:
            if p.get("symbol") != symbol:
                continue
            amt = float(p.get("positionAmt", 0))
            if hedge_mode:
                ps = p.get("positionSide", "")
                if side == "LONG" and ps == "LONG" and amt > 0:
                    return abs(amt)
                if side == "SHORT" and ps == "SHORT" and amt < 0:
                    return abs(amt)
            else:
                if side == "LONG" and amt > 0:
                    return abs(amt)
                if side == "SHORT" and amt < 0:
                    return abs(amt)
    except Exception as e:
        log("POS RISK ERR: %s" % e)
    return 0.0

def set_leverage(symbol, lev):
    try:
        binance_request("POST", "/fapi/v1/leverage", {"symbol": symbol, "leverage": int(lev)})
    except Exception as e:
        log("LEV ERR: %s" % e)

def place_market(symbol, side, qty, position_side=None, reduce_only=False):
    params = {
        "symbol": symbol,
        "side": side,
        "type": "MARKET",
        "quantity": qty,
    }
    if position_side:
        params["positionSide"] = position_side
    if reduce_only:
        params["reduceOnly"] = "true"
    return binance_request("POST", "/fapi/v1/order", params)

def fetch_px(symbol):
    try:
        url = "https://fapi.binance.com/fapi/v1/ticker/price?symbol=" + symbol
        req = urllib.request.Request(url, headers={"Connection": "close", "User-Agent": "hc"})
        with urllib.request.urlopen(req, timeout=2) as r:
            px = float(json.loads(r.read().decode("utf-8"))["price"])
            last_px[symbol] = px
            return px, "live"
    except Exception:
        return last_px.get(symbol, FALLBACK[symbol]), "fallback"

def cb_check():
    now = time.time()
    if cb_state["locked_until"] > now:
        return False
    if cb_state["fails"] >= CB_THRESHOLD:
        cb_state["locked_until"] = now + CB_COOLDOWN
        cb_state["fails"] = 0
        log("CIRCUIT BREAKER %ds" % CB_COOLDOWN)
        return False
    return True

def cb_hit():
    cb_state["fails"] += 1

def cb_reset():
    cb_state["fails"] = 0

def open_pos(symbol, side, px, src):
    global balance
    with lock:
        if any(p.get("status") == "OPEN" for p in positions.values()):
            return
        if not cb_check():
            return

        real = get_balance_usdt()
        if real > 0:
            balance = real
            log("BAL SYNC %.2f" % balance)

        margin = balance * RISK
        if margin < MIN_MARGIN:
            log("SKIP margin %.2f" % margin)
            return

        notional = min(margin * LEV, MAX_POS_USDT)
        margin = notional / LEV
        qty = round(notional / px, QTY_PREC.get(symbol, 2))
        if qty <= 0:
            return

        set_leverage(symbol, int(LEV))
        binance_side = "BUY" if side == "LONG" else "SELL"
        pos_side = side if hedge_mode else None

        try:
            res = place_market(symbol, binance_side, qty, pos_side)
            oid = res.get("orderId", 0)
            exec_px = float(res.get("avgPrice") or px)
            if exec_px <= 0:
                exec_px = px
            cb_reset()
            log("ACK oid=%s avg=%.4f qty=%s %s" % (oid, exec_px, qty, pos_side or "ONEWAY"))
        except Exception as e:
            cb_hit()
            log("OPEN FAIL %s" % e)
            return

        px = exec_px
        open_fee = notional * FEE
        balance -= open_fee

        if side == "LONG":
            tp = px * (1 + TP_P / 100)
            sl = px * (1 - SL_P / 100)
        else:
            tp = px * (1 - TP_P / 100)
            sl = px * (1 + SL_P / 100)

        pid = "s%d" % int(time.time() * 1000)
        positions[pid] = {
            "id": pid, "symbol": symbol, "side": side, "status": "OPEN",
            "entry": px, "qty": qty, "margin": margin, "notional": notional,
            "tp": tp, "sl": sl, "open_fee": open_fee, "ticks": 0, "src": src,
            "binance_id": oid, "pos_side": pos_side
        }
        log(
            "OPEN %s %s entry=%.4f (%s) margin=%.2f notional=%.2f lev=%.0fx "
            "TP=%.4f (+%.2f%%) SL=%.4f fee=%.4f bal=%.2f oid=%s" % (
                side, symbol, px, src, margin, notional, LEV, tp, TP_P, sl, open_fee, balance, oid)
        )

def close_pos(pos, px, reason, src):
    global balance, peak
    close_side = "SELL" if pos["side"] == "LONG" else "BUY"
    pos_side = pos.get("pos_side")

    real_qty = get_position_amt(pos["symbol"], pos["side"])
    if real_qty <= 0:
        log("CLOSE SKIP no position on exchange")
        with lock:
            if pos["id"] in positions:
                del positions[pos["id"]]
        return

    qty = min(pos["qty"], real_qty)
    qty = round(qty, QTY_PREC.get(pos["symbol"], 2))
    if qty <= 0:
        return

    try:
        res = place_market(pos["symbol"], close_side, qty, pos_side, reduce_only=True)
        px = float(res.get("avgPrice") or px)
        cb_reset()
        log("CLOSE ACK oid=%s avg=%.4f qty=%s" % (res.get("orderId"), px, qty))
    except Exception as e:
        log("reduceOnly FAIL -> plain: %s" % e)
        try:
            res = place_market(pos["symbol"], close_side, qty, pos_side, reduce_only=False)
            px = float(res.get("avgPrice") or px)
            cb_reset()
            log("CLOSE ACK plain oid=%s avg=%.4f" % (res.get("orderId"), px))
        except Exception as e2:
            cb_hit()
            log("CLOSE FAIL %s" % e2)
            return

    close_fee = qty * px * FEE
    if pos["side"] == "LONG":
        raw = (px - pos["entry"]) * qty
        move = (px - pos["entry"]) / pos["entry"] * 100
    else:
        raw = (pos["entry"] - px) * qty
        move = (pos["entry"] - px) / pos["entry"] * 100
    fees = pos["open_fee"] + close_fee
    net = raw - close_fee

    with lock:
        balance += pos["margin"] + net
        real = get_balance_usdt()
        if real > 0:
            balance = real
        peak = max(peak, balance)
        dd = (peak - balance) / peak * 100 if peak else 0
        m_pct = net / pos["margin"] * 100 if pos["margin"] else 0
        pos["status"] = "CLOSED"
        rec = {
            "id": pos["id"], "symbol": pos["symbol"], "side": pos["side"], "reason": reason,
            "entry": pos["entry"], "exit": px, "move_pct": round(move, 4),
            "open_fee": round(pos["open_fee"], 4), "close_fee": round(close_fee, 4),
            "total_fees": round(fees, 4), "raw_pnl": round(raw, 4), "net_pnl": round(net, 4),
            "margin_pnl_pct": round(m_pct, 2), "balance": round(balance, 2),
            "dd_pct": round(dd, 2), "px_src": src
        }
        journal.insert(0, rec)
        if len(journal) > 100:
            journal.pop()
        if pos["id"] in positions:
            del positions[pos["id"]]
        bal = balance

    log(
        "CLOSE %s %s %s exit=%.4f (%s) move=%.3f%% fees=%.4f NET=%.4f (%.1f%%marj) bal=%.2f DD=%.1f%%" % (
            pos["side"], pos["symbol"], reason, px, src, move, fees, net, rec["margin_pnl_pct"], bal, rec["dd_pct"])
    )

def check_exit(pos, px):
    if pos["side"] == "LONG":
        if px >= pos["tp"]:
            return "TP"
        if px <= pos["sl"]:
            return "SL"
    else:
        if px <= pos["tp"]:
            return "TP"
        if px >= pos["sl"]:
            return "SL"
    return None

def loop():
    global hedge_mode, balance, peak
    try:
        hedge_mode = get_position_mode()
        log("MODE %s" % ("HEDGE" if hedge_mode else "ONE-WAY"))
    except Exception as e:
        log("MODE FAIL %s" % e)

    real = get_balance_usdt()
    if real > 0:
        balance = real
        peak = real

    log("START LIVE bal=%.2f risk=%.0f%% lev=%.0fx TP=%.2f%% SL=%.2f%% hold=%d" % (
        balance, RISK * 100, LEV, TP_P, SL_P, HOLD_MAX))

    i = 0
    idle = 0
    while True:
        try:
            state["i"] = i
            state["last"] = time.time()
            log("hb i=%d bal=%.2f" % (i, balance))

            with lock:
                opens = [p for p in positions.values() if p.get("status") == "OPEN"]

            if opens:
                pos = opens[0]
                pos["ticks"] += 1
                px, src = fetch_px(pos["symbol"])
                reason = check_exit(pos, px)
                if reason:
                    close_pos(pos, px, reason, src)
                    idle = COOLDOWN
                elif pos["ticks"] >= HOLD_MAX:
                    close_pos(pos, px, "TIME", src)
                    idle = COOLDOWN
                else:
                    dtp = abs(px - pos["tp"]) / pos["entry"] * 100
                    dsl = abs(px - pos["sl"]) / pos["entry"] * 100
                    log("HOLD %s %s t=%d/%d px=%.4f dTP=%.3f dSL=%.3f" % (
                        pos["side"], pos["symbol"], pos["ticks"], HOLD_MAX, px, dtp, dsl))
            else:
                if idle > 0:
                    idle -= 1
                else:
                    sym = SYMBOLS[i % len(SYMBOLS)]
                    px, src = fetch_px(sym)
                    side = "LONG" if i % 2 == 0 else "SHORT"
                    open_pos(sym, side, px, src)
            i += 1
        except Exception as e:
            log("ERR %s: %s" % (type(e).__name__, e))
        time.sleep(INTERVAL)

@app.route("/health")
def health():
    return jsonify({"ok": 1, "i": state["i"], "age": round(time.time() - state["last"], 1)})

@app.route("/status")
def status():
    with lock:
        n = sum(1 for p in positions.values() if p.get("status") == "OPEN")
        return jsonify({"balance": round(balance, 2), "open": n, "lev": LEV, "trades": len(journal), "mode": "LIVE"})

@app.route("/journal")
def journal_ep():
    with lock:
        return jsonify(list(journal[:25]))

@app.route("/logs")
def logs_ep():
    with lock:
        return jsonify(list(logs[:50]))

@app.route("/summary")
def summary():
    with lock:
        jn = list(journal)
    wins = [x for x in jn if x.get("net_pnl", 0) > 0]
    fees = sum(x.get("total_fees", 0) for x in jn)
    net = sum(x.get("net_pnl", 0) for x in jn)
    return jsonify({
        "balance": round(balance, 2),
        "net_pnl_total": round(net, 4),
        "total_fees_paid": round(fees, 4),
        "trades": len(jn),
        "wins": len(wins),
        "losses": len(jn) - len(wins),
        "win_rate": round(100.0 * len(wins) / len(jn), 1) if jn else 0,
        "leverage": LEV,
        "mode": "LIVE"
    })

if __name__ == "__main__":
    threading.Thread(target=loop, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True, use_reloader=False)
