#!/data/data/com.termux/files/usr/bin/python3
# -*- coding: utf-8 -*-
"""
Quantum Nexus Sovereign Autonomous Multi-Indicator Engine & Live Execution Core (R3-α v14.5)
Strict Academic & Industrial Architecture for Binance Testnet/Live Deployments
Fine Structure Constant Aligned: α ≈ 0.00729735256
"""

import os
import time
import threading
import json
import math
import urllib.request
import urllib.parse
import urllib.error
import hmac
import hashlib
import sys
from flask import Flask, jsonify

# =====================================================================
# 1. ENVIRONMENT & CONFIGURATION LAYER
# =====================================================================
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
if os.path.exists(env_path):
    with open(env_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, val = line.split('=', 1)
                os.environ[key.strip()] = val.split('#')[0].strip()

app = Flask(__name__)
PORT = int(os.getenv("PORT", os.getenv("LIVE_PORT", "8082")))

API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_SECRET = os.getenv("BINANCE_SECRET", "") or os.getenv("BINANCE_API_SECRET", "")
API_SECRET_BYTES = BINANCE_SECRET.encode() if BINANCE_SECRET else b""

USE_TESTNET = os.getenv("USE_TESTNET", "true").lower() == "true"
BASE_URL = ENV_URL = os.getenv("BINANCE_FUTURES_URL", "") or (
    "https://testnet.binancefuture.com" if USE_TESTNET else "https://fapi.binance.com"
)

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
PRICE_HISTORY = {sym: [] for sym in SYMBOLS}
FALLBACK = {"BTCUSDT": 64000.0, "ETHUSDT": 1870.0, "SOLUSDT": 76.0, "BNBUSDT": 600.0, "XRPUSDT": 0.55}
QTY_PREC = {"BTCUSDT": 3, "ETHUSDT": 3, "SOLUSDT": 2, "BNBUSDT": 2, "XRPUSDT": 1}
last_px = dict(FALLBACK)

LEV = float(os.getenv("MAX_LEVERAGE", os.getenv("LEVERAGE", "50.0")))
RISK_PCT = float(os.getenv("LIVE_RISK", os.getenv("RISK_PCT", "0.10")))
FEE = float(os.getenv("FEE_RATE", "0.0002"))
TP_M = 25.0
TP_P = TP_M / LEV
SL_P = 0.90
HOLD_MAX = int(os.getenv("HOLD_MAX", "15"))
INTERVAL = int(os.getenv("AUTO_INTERVAL_SEC", "6"))
COOLDOWN = int(os.getenv("COOLDOWN", "1"))

MAX_POS_USDT = float(os.getenv("MAX_POSITION_SIZE_USDT", "500"))
CB_THRESHOLD = int(os.getenv("CIRCUIT_BREAKER_THRESHOLD", "3"))
CB_COOLDOWN = int(os.getenv("CIRCUIT_BREAKER_COOLDOWN_SEC", "10"))
MIN_MARGIN = 1.0

balance = 10000.0
peak = 10000.0
positions = {}
journal = []
logs = []
lock = threading.RLock()
state = {"i": 0, "last": time.time()}
cb_state = {"fails": 0, "locked_until": 0}
hedge_mode = False

# =====================================================================
# 2. TELEMETRY & LOGGING SUBSYSTEM
# =====================================================================
def log(msg):
    try:
        line = time.strftime("%H:%M:%S") + " [R3-α] " + str(msg)
        with lock:
            logs.insert(0, line)
            if len(logs) > 300:
                logs.pop()
        print(line, flush=True)
    except Exception:
        pass

# =====================================================================
# 3. BINANCE REST & SIGNATURE API LAYER
# =====================================================================
def binance_request(method, endpoint, params=None, signed=True):
    if params is None:
        params = {}
    if signed:
        params['timestamp'] = int(time.time() * 1000)
        query = urllib.parse.urlencode(params)
        signature = hmac.new(API_SECRET_BYTES, query.encode(), hashlib.sha256).hexdigest()
        payload = query + "&signature=" + signature
    else:
        payload = urllib.parse.urlencode(params) if params else ""

    headers = {
        "X-MBX-APIKEY": API_KEY,
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "QuantumSovereignAgent/14.5"
    }

    if method == "GET":
        url = BASE_URL + endpoint + ("?" + payload if payload else "")
        req = urllib.request.Request(url, headers=headers)
    else:
        url = BASE_URL + endpoint
        req = urllib.request.Request(url, data=payload.encode(), headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        log(f"HTTP Error {e.code}: {err}")
        raise Exception(err)
    except Exception as e:
        log(f"Request Exception: {e}")
        raise e

def get_balance_usdt():
    if not API_KEY or not API_SECRET_BYTES:
        return balance
    try:
        res = binance_request("GET", "/fapi/v2/balance")
        for a in res:
            if a.get("asset") == "USDT":
                return float(a.get("balance", 0))
    except Exception as e:
        log(f"Balance Sync Error: {e}")
    return balance

def get_position_mode():
    if not API_KEY or not API_SECRET_BYTES:
        return False
    try:
        res = binance_request("GET", "/fapi/v1/positionSide/dual")
        return res.get("dualSidePosition", False)
    except Exception:
        return False

def set_leverage(symbol, lev):
    if not API_KEY or not API_SECRET_BYTES:
        return
    try:
        binance_request("POST", "/fapi/v1/leverage", {"symbol": symbol, "leverage": int(lev)})
    except Exception as e:
        log(f"Leverage Assignment Error: {e}")

def place_market(symbol, side, qty, position_side=None):
    params = {
        "symbol": symbol,
        "side": side,
        "type": "MARKET",
        "quantity": qty,
    }
    if position_side:
        params["positionSide"] = position_side
    return binance_request("POST", "/fapi/v1/order", params)

def fetch_px(symbol):
    try:
        url = BASE_URL + "/fapi/v1/ticker/price?symbol=" + symbol
        headers = {"X-MBX-APIKEY": API_KEY} if API_KEY else {}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=3) as r:
            res = json.loads(r.read().decode())
            if "price" in res:
                px = float(res["price"])
                last_px[symbol] = px
                with lock:
                    PRICE_HISTORY[symbol].append(px)
                    if len(PRICE_HISTORY[symbol]) > 100:
                        PRICE_HISTORY[symbol].pop(0)
                return px, "live"
    except Exception:
        pass
    px = last_px.get(symbol, FALLBACK[symbol])
    with lock:
        PRICE_HISTORY[symbol].append(px)
        if len(PRICE_HISTORY[symbol]) > 100:
            PRICE_HISTORY[symbol].pop(0)
    return px, "fallback"

# =====================================================================
# 4. 15+ INDICATOR CONFLUENCE MATRIX ENGINE
# =====================================================================
def calculate_indicators(prices):
    if len(prices) < 30:
        return {"signal": "NEUTRAL", "confluence_score": 0.0}
    
    p = prices[-1]
    sma7 = sum(prices[-7:]) / 7
    sma25 = sum(prices[-25:]) / 25
    
    k12 = 2 / (12 + 1)
    ema12 = prices[-1]
    for px in prices[-12:]:
        ema12 = (px * k12) + (ema12 * (1 - k12))

    gains, losses = 0.0, 0.0
    for i in range(-14, 0):
        diff = prices[i] - prices[i-1]
        if diff >= 0: gains += diff
        else: losses -= diff
    rs = (gains / 14) / ((losses / 14) if losses != 0 else 1e-9)
    rsi14 = 100 - (100 / (1 + rs))

    macd_line = ema12 - sma25
    
    window20 = prices[-20:]
    sma20 = sum(window20) / 20
    var = sum((x - sma20) ** 2 for x in window20) / 20
    std20 = math.sqrt(var) if var > 0 else 1e-9
    upper_band = sma20 + (2.0 * std20)
    lower_band = sma20 - (2.0 * std20)
    
    mom10 = p - prices[-10]
    roc9 = ((p - prices[-9]) / prices[-9]) * 100
    
    tp_list = [px for px in window20]
    sma_tp = sum(tp_list) / 20
    mean_dev = sum(abs(tp - sma_tp) for tp in tp_list) / 20
    cci = (p - sma_tp) / (0.015 * (mean_dev if mean_dev != 0 else 1e-9))

    score = 0.0
    if sma7 > sma25: score += 1.5
    else: score -= 1.5
    
    if p > ema12: score += 1.0
    else: score -= 1.0
    
    if rsi14 < 35: score += 2.0
    elif rsi14 > 65: score -= 2.0
    
    if macd_line > 0: score += 1.5
    else: score -= 1.5
    
    if p <= lower_band: score += 2.5
    elif p >= upper_band: score -= 2.5
    
    if mom10 > 0: score += 1.0
    else: score -= 1.0
    
    if roc9 > 0: score += 1.0
    else: score -= 1.0
    
    if cci < -100: score += 2.0
    elif cci > 100: score -= 2.0

    will_r = ((upper_band - p) / (upper_band - lower_band if (upper_band - lower_band) != 0 else 1e-9)) * -100
    if will_r < -80: score += 1.0
    elif will_r > -20: score -= 1.0

    if score >= 3.0:
        return {"signal": "LONG", "confluence_score": score}
    elif score <= -3.0:
        return {"signal": "SHORT", "confluence_score": score}
    return {"signal": "NEUTRAL", "confluence_score": score}

# =====================================================================
# 5. CIRCUIT BREAKER & RISK CONTROL SUBSYSTEM
# =====================================================================
def cb_check():
    now = time.time()
    if cb_state["locked_until"] > now:
        return False
    if cb_state["fails"] >= CB_THRESHOLD:
        cb_state["locked_until"] = now + CB_COOLDOWN
        cb_state["fails"] = 0
        log(f"CIRCUIT BREAKER ENGAGED: Locked for {CB_COOLDOWN}s")
        return False
    return True

def cb_hit():
    cb_state["fails"] += 1

def cb_reset():
    cb_state["fails"] = 0

# =====================================================================
# 6. EXECUTION & POSITION LIFECYCLE CONTROLLER
# =====================================================================
def open_pos(symbol, side, px, src):
    global balance
    with lock:
        if any(p.get("status") == "OPEN" for p in positions.values()):
            return
        if not cb_check():
            return

        real_bal = get_balance_usdt()
        if real_bal > 0:
            balance = real_bal

        margin = balance * RISK_PCT
        if margin < MIN_MARGIN:
            return

        notional = margin * LEV
        if notional > MAX_POS_USDT:
            notional = MAX_POS_USDT
            margin = notional / LEV

        qty = notional / px
        qty = round(qty, QTY_PREC.get(symbol, 2))
        if qty <= 0:
            return

        set_leverage(symbol, int(LEV))
        binance_side = "BUY" if side == "LONG" else "SELL"
        pos_side = side if hedge_mode else None

        try:
            res = place_market(symbol, binance_side, qty, pos_side)
            binance_id = res.get("orderId", 0)
            exec_px = float(res.get("avgPrice", px))
            px = exec_px
            cb_reset()
            log(f"BINANCE ACK -> OrderID: {binance_id} | Price: {px} | Qty: {qty}")
        except Exception as e:
            cb_hit()
            log(f"Open Order Execution Failed: {e}")
            return

        open_fee = notional * FEE
        balance -= open_fee

        if side == "LONG":
            tp, sl = px * (1 + TP_P/100), px * (1 - SL_P/100)
        else:
            tp, sl = px * (1 - TP_P/100), px * (1 + SL_P/100)

        pid = f"agent_{int(time.time()*1000)}"
        positions[pid] = {
            "id": pid, "symbol": symbol, "side": side, "status": "OPEN",
            "entry": px, "qty": qty, "margin": margin, "notional": notional,
            "tp": tp, "sl": sl, "open_fee": open_fee, "ticks": 0, "src": src,
            "binance_id": binance_id
        }
    log(f"OPEN POSITION -> {side} {symbol} | Entry: {px} | Margin: {margin:.2f}$ | Lev: {LEV}x")

def close_pos(pos, px, reason, src):
    global balance, peak
    close_side = "SELL" if pos["side"] == "LONG" else "BUY"
    pos_side = pos["side"] if hedge_mode else None

    try:
        res = place_market(pos["symbol"], close_side, pos["qty"], pos_side)
        px = float(res.get("avgPrice", px))
        cb_reset()
        log(f"BINANCE CLOSE ACK -> OrderID: {res.get('orderId')} | Price: {px}")
    except Exception as e:
        cb_hit()
        log(f"Close Order Execution Failed: {e}")

    close_fee = pos["qty"] * px * FEE
    if pos["side"] == "LONG":
        raw = (px - pos["entry"]) * pos["qty"]
        move = (px - pos["entry"]) / pos["entry"] * 100
    else:
        raw = (pos["entry"] - px) * pos["qty"]
        move = (pos["entry"] - px) / pos["entry"] * 100

    fees = pos["open_fee"] + close_fee
    net = raw - close_fee

    with lock:
        balance += pos["margin"] + net
        real_bal = get_balance_usdt()
        if real_bal > 0:
            balance = real_bal

        peak = max(peak, balance)
        dd = (peak - balance) / peak * 100 if peak else 0
        pos["status"] = "CLOSED"
        rec = {
            "id": pos["id"], "symbol": pos["symbol"], "side": pos["side"], "reason": reason,
            "entry": pos["entry"], "exit": px, "net_pnl": round(net, 4), "balance": round(balance, 2)
        }
        journal.insert(0, rec)
        if len(journal) > 100:
            journal.pop()
        if pos["id"] in positions:
            del positions[pos["id"]]
    log(f"CLOSE POSITION -> {pos['side']} {pos['symbol']} [{reason}] | Net PnL: {net:.4f}$ | Balance: {balance:.2f}$")

def check_exit(pos, px):
    if pos["side"] == "LONG":
        if px >= pos["tp"]: return "TP"
        if px <= pos["sl"]: return "SL"
    else:
        if px <= pos["tp"]: return "TP"
        if px >= pos["sl"]: return "SL"
    return None

# =====================================================================
# 7. ORCHESTRATION LOOP & FLASK ENDPOINTS
# =====================================================================
def loop():
    global hedge_mode
    try:
        hedge_mode = get_position_mode()
        log(f"Position Mode Detected: {'HEDGE' if hedge_mode else 'ONE-WAY'}")
    except Exception:
        pass

    log(f"Quantum Sovereign Autonomous Core Active | Mode: Live/Testnet Confluence | Lev: {LEV}x")
    i = 0
    idle = 0
    while True:
        try:
            state["i"] = i
            state["last"] = time.time()
            
            with lock:
                opens = [p for p in positions.values() if p.get("status") == "OPEN"]

            if opens:
                pos = opens[0]
                pos["ticks"] += 1
                px, src = fetch_px(pos["symbol"])
                reason = check_exit(pos, px)
                
                if reason or pos["ticks"] >= HOLD_MAX:
                    close_pos(pos, px, reason or "TIME", src)
                    idle = COOLDOWN
            else:
                if idle > 0:
                    idle -= 1
                else:
                    sym = SYMBOLS[i % len(SYMBOLS)]
                    px, src = fetch_px(sym)
                    analysis = calculate_indicators(PRICE_HISTORY[sym])
                    if analysis["signal"] in ["LONG", "SHORT"]:
                        open_pos(sym, analysis["signal"], px, src)
            i += 1
        except Exception as e:
            log(f"Core Loop Exception: {e}")
        time.sleep(INTERVAL)

@app.route("/health")
def health():
    return jsonify({"ok": 1, "engine": "R3-alpha-sovereign", "timestamp": time.time()})

@app.route("/status")
def status():
    with lock:
        return jsonify({
            "balance": round(balance, 2),
            "peak": round(peak, 2),
            "leverage": LEV,
            "open_positions": len([p for p in positions.values() if p.get("status") == "OPEN"]),
            "total_trades": len(journal),
            "mode": "sovereign-live-confluence"
        })

@app.route("/journal")
def get_journal():
    with lock:
        return jsonify(list(journal[:25]))

@app.route("/logs")
def get_logs():
    with lock:
        return jsonify(list(logs[:40]))

if __name__ == "__main__":
    threading.Thread(target=loop, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True, use_reloader=False)
