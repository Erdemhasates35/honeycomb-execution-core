#!/data/data/com.termux/files/usr/bin/python3
# -*- coding: utf-8 -*-
"""HELIX COIN-M — dapi only (https://dapi.binance.com). USD_PERP symbols."""
from __future__ import annotations
import os, sys, time, threading
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from live.kernel import LiveKernel, load_env, ema, rsi, atr

ENV = load_env()
PORT = int(ENV.get("HELIX_PORT", "8092"))
SYMBOLS = [s.strip().upper() for s in (ENV.get("COIN_SYMBOLS") or "BTCUSD_PERP,ETHUSD_PERP").split(",") if s.strip()]
RISK = float(ENV.get("LIVE_RISK", "0.10"))
LEV = min(50, max(1, int(float(ENV.get("MAX_LEVERAGE", "15")))))
HOLD_MAX = int(ENV.get("HOLD_MAX", "20"))
INTERVAL = int(ENV.get("AUTO_INTERVAL_SEC", "6"))
MAX_POS = float(ENV.get("MAX_POSITION_SIZE_USDT", "150"))
FEE = float(ENV.get("FEE_RATE", "0.0004"))
SL_P = float(ENV.get("SL_P", "0.80"))
NET_TARGET = float(ENV.get("NET_MARGIN_TARGET_PCT", "10.0"))
logs, journal, positions = [], [], {}
lock = threading.RLock()
state = {"i": 0, "last": time.time(), "engine": "HELIX-COIN", "on": True}

def log(msg):
    line = time.strftime("%H:%M:%S") + " [HELIX] " + str(msg)
    with lock:
        logs.insert(0, line)
        if len(logs) > 400: logs.pop()
    print(line, flush=True)

def signal(k, symbol):
    closes, _ = k.klines(symbol, "1m", 60)
    if len(closes) < 30: return None, "data"
    e9, e21, r, a = ema(closes, 9), ema(closes, 21), rsi(closes, 14), atr(closes, 14)
    if None in (e9, e21, r, a): return None, "ind"
    atr_pct = (a / closes[-1]) * 100
    if atr_pct < 0.06: return None, "low_vol"
    if e9 > e21 and 40 <= r <= 65: return "LONG", "EMA+RSI"
    if e9 < e21 and 35 <= r <= 60: return "SHORT", "EMA+RSI"
    return None, "filter"

def px_of(k, symbol):
    bid, ask, mid = k.book(symbol)
    return mid

def loop():
    # CRITICAL: venue=coin → dapi.binance.com — never fapi for USD_PERP
    k = LiveKernel(venue="coin", env=ENV, log_fn=log)
    k.sync_time()
    bal = k.balance_usdt()
    log("START HELIX-COIN bal=%.6f lev=%dx (dapi only) symbols=%s" % (bal, LEV, ",".join(SYMBOLS)))
    i, idle, last_sync = 0, 0, time.time()
    while True:
        try:
            if not state.get("on", True):
                time.sleep(2); continue
            if time.time() - last_sync > 1800:
                k.sync_time(); last_sync = time.time()
            state["i"], state["last"] = i, time.time()
            with lock:
                opens = [p for p in positions.values() if p.get("status") == "OPEN"]
            if opens:
                pos = opens[0]
                pos["ticks"] = pos.get("ticks", 0) + 1
                try:
                    px = px_of(k, pos["symbol"])
                except Exception as e:
                    log("HOLD halt: %s" % e); i += 1; time.sleep(INTERVAL); continue
                reason = None
                if pos["side"] == "LONG":
                    if px >= pos["tp"]: reason = "TP"
                    elif px <= pos["sl"]: reason = "SL"
                else:
                    if px <= pos["tp"]: reason = "TP"
                    elif px >= pos["sl"]: reason = "SL"
                if reason is None and pos["ticks"] >= HOLD_MAX:
                    reason = "TIME"
                if reason:
                    try:
                        fill = k.close_market(pos["symbol"], pos["side"], pos["qty"], pos.get("pos_side"))
                        net = fill.get("rp", 0)
                        with lock:
                            journal.insert(0, {"symbol": pos["symbol"], "side": pos["side"], "reason": reason,
                                "entry": pos["entry"], "exit": fill["avg"], "net_pnl": round(net, 8)})
                            positions.pop(pos["id"], None)
                        log("CLOSED %s %s %s RP=%.8f" % (pos["side"], pos["symbol"], reason, net))
                    except Exception as e:
                        log("CLOSE FAIL: %s" % e)
                    idle = 2
            else:
                if idle > 0:
                    idle -= 1
                else:
                    sym = SYMBOLS[i % len(SYMBOLS)]
                    side, detail = signal(k, sym)
                    if side:
                        try:
                            closes, _ = k.klines(sym, "1m", 40)
                            a = atr(closes, 14) or 0
                            px = px_of(k, sym)
                            atr_pct = (a / px) * 100 if px else 0.4
                            tp_pct = max(NET_TARGET / LEV + 2 * FEE * 100, atr_pct * 0.9)
                            sl_pct = max(SL_P, atr_pct * 1.6)
                            opened = k.open_market(sym, side, RISK, LEV, tp_pct, sl_pct, max_notional=MAX_POS)
                            pid = "h%d" % int(time.time() * 1000)
                            with lock:
                                positions[pid] = {"id": pid, "status": "OPEN", "ticks": 0, "mfe": 0.0, **opened}
                            log("OPENED %s %s %s" % (side, sym, detail))
                        except Exception as e:
                            log("OPEN skip %s: %s" % (sym, e))
                    elif i % 12 == 0:
                        log("scan %s: %s" % (sym, detail))
            i += 1
        except Exception as e:
            log("loop %s: %s" % (type(e).__name__, e))
        time.sleep(INTERVAL)

def run_flask():
    try:
        from flask import Flask, jsonify
    except ImportError:
        log("flask yok — sadece loop"); return
    app = Flask(__name__)
    @app.route("/health")
    def health():
        return jsonify({"ok": 1, "engine": "HELIX-COIN", "i": state["i"]})
    @app.route("/status")
    def status():
        with lock:
            return jsonify({"engine": "HELIX-COIN", "open": sum(1 for p in positions.values() if p.get("status")=="OPEN"),
                            "trades": len(journal), "on": state.get("on", True)})
    @app.route("/journal")
    def j():
        with lock:
            return jsonify(list(journal[:30]))
    @app.route("/logs")
    def l():
        with lock:
            return jsonify(list(logs[:60]))
    @app.route("/on", methods=["POST", "GET"])
    def on():
        state["on"] = True
        return jsonify({"on": True})
    @app.route("/off", methods=["POST", "GET"])
    def off():
        state["on"] = False
        return jsonify({"on": False})
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True, use_reloader=False)

if __name__ == "__main__":
    threading.Thread(target=loop, daemon=True).start()
    run_flask()
    while True:
        time.sleep(3600)
