#!/data/data/com.termux/files/usr/bin/python3
# -*- coding: utf-8 -*-
"""MAKER SNIPER — GTX post-only. Maker fee edge. No chase unless SNIPER_CHASE=1."""
from __future__ import annotations
import os, sys, time, threading
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from live.kernel import LiveKernel, load_env, ema, rsi

ENV = load_env()
PORT = int(ENV.get("SNIPER_PORT", "8093"))
VENUE = (ENV.get("VENUE") or "usdt").strip().lower()
SYMBOLS = [s.strip().upper() for s in ((ENV.get("COIN_SYMBOLS") if VENUE == "coin" else ENV.get("LIVE_SYMBOLS")) or ("BTCUSD_PERP" if VENUE == "coin" else "BNBUSDT,ETHUSDT,SOLUSDT")).split(",") if s.strip()]
RISK = float(ENV.get("LIVE_RISK", "0.10"))
LEV = min(50, max(1, int(float(ENV.get("MAX_LEVERAGE", "15")))))
HOLD_MAX = int(ENV.get("HOLD_MAX", "25"))
INTERVAL = int(ENV.get("AUTO_INTERVAL_SEC", "4"))
MAX_POS = float(ENV.get("MAX_POSITION_SIZE_USDT", "120"))
SL_P = float(ENV.get("SL_P", "0.60"))
TP_P = float(ENV.get("TP_M", "12.0")) / max(LEV, 1)
CHASE = ENV.get("SNIPER_CHASE", "0").strip() in ("1", "true", "True")
logs, journal, positions = [], [], {}
lock = threading.RLock()
state = {"i": 0, "last": time.time(), "engine": "MAKER-SNIPER", "on": True}

def log(msg):
    line = time.strftime("%H:%M:%S") + " [SNIPER] " + str(msg)
    with lock:
        logs.insert(0, line)
        if len(logs) > 400: logs.pop()
    print(line, flush=True)

def bias(k, symbol):
    closes, _ = k.klines(symbol, "1m", 40)
    if len(closes) < 25: return None
    e9, e21, r = ema(closes, 9), ema(closes, 21), rsi(closes, 14)
    if None in (e9, e21, r): return None
    if e9 > e21 and r < 65: return "LONG"
    if e9 < e21 and r > 35: return "SHORT"
    return None

def loop():
    k = LiveKernel(venue=VENUE, env=ENV, log_fn=log)
    k.sync_time(); k.load_exchange_info(SYMBOLS); k.position_mode()
    log("START MAKER-SNIPER venue=%s lev=%dx GTX" % (VENUE, LEV))
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
                try: px = k.price(pos["symbol"])
                except Exception as e:
                    log("HOLD halt: %s" % e); i += 1; time.sleep(INTERVAL); continue
                reason = None
                if pos["side"] == "LONG":
                    if px >= pos["tp"]: reason = "TP"
                    elif px <= pos["sl"]: reason = "SL"
                else:
                    if px <= pos["tp"]: reason = "TP"
                    elif px >= pos["sl"]: reason = "SL"
                if reason is None and pos["ticks"] >= HOLD_MAX: reason = "TIME"
                if reason:
                    try:
                        fill = k.close_market(pos["symbol"], pos["side"], pos["qty"], pos.get("pos_side"))
                        with lock:
                            journal.insert(0, {"symbol": pos["symbol"], "side": pos["side"], "reason": reason,
                                "entry": pos["entry"], "exit": fill["avg"], "net_pnl": round(fill["rp"], 6), "maker": True})
                            positions.pop(pos["id"], None)
                        log("CLOSED %s %s %s RP=%.6f" % (pos["side"], pos["symbol"], reason, fill["rp"]))
                    except Exception as e: log("CLOSE FAIL: %s" % e)
                    idle = 2
            else:
                if idle > 0: idle -= 1
                else:
                    sym = SYMBOLS[i % len(SYMBOLS)]
                    side = bias(k, sym)
                    if side:
                        try:
                            book = k.book(sym)
                            price = book["bid"] if side == "LONG" else book["ask"]
                            notional = min(k.balance() * RISK * LEV, MAX_POS)
                            f = k.get_filters(sym)
                            qty = k.round_step(notional / price, f["stepSize"])
                            if VENUE == "coin": qty = max(1, int(round(qty)))
                            if qty < f["minQty"]: raise RuntimeError("qty below min")
                            veto = k.funding_veto(sym, side)
                            if veto: raise RuntimeError(veto)
                            if not k.flock.acquire(False): raise RuntimeError("single_flight locked")
                            try:
                                k.set_margin_type(sym); k.set_leverage(sym, LEV)
                                binance_side = "BUY" if side == "LONG" else "SELL"
                                pos_side = side if k.hedge_mode else None
                                res = k.place_limit_gtx(sym, binance_side, qty, price, pos_side)
                                oid = res.get("orderId")
                                time.sleep(1.2)
                                try:
                                    od = k._http("GET", k.v["order"], {"symbol": sym, "orderId": oid}, signed=True, weight=1)
                                    status = od.get("status", ""); avg = float(od.get("avgPrice") or 0)
                                    filled = float(od.get("executedQty") or 0)
                                except Exception:
                                    status, avg, filled = "NEW", 0.0, 0.0
                                if status in ("NEW", "PARTIALLY_FILLED") and filled <= 0:
                                    try: k._http("DELETE", k.v["order"], {"symbol": sym, "orderId": oid}, signed=True, weight=1)
                                    except Exception: pass
                                    if CHASE:
                                        opened = k.open_market(sym, side, notional, LEV, TP_P, SL_P)
                                        pid = "m%d" % int(time.time() * 1000)
                                        with lock: positions[pid] = {"id": pid, "status": "OPEN", "ticks": 0, **opened}
                                    else: log("GTX unfilled — cancel")
                                elif filled > 0 or avg > 0:
                                    fill = k.resolve_fill(sym, oid, price, qty)
                                    entry = fill["avg"]
                                    tp = entry * (1 + TP_P / 100) if side == "LONG" else entry * (1 - TP_P / 100)
                                    sl = entry * (1 - SL_P / 100) if side == "LONG" else entry * (1 + SL_P / 100)
                                    k.place_protect(sym, side, entry, tp, sl, pos_side)
                                    pid = "m%d" % int(time.time() * 1000)
                                    with lock:
                                        positions[pid] = {"id": pid, "status": "OPEN", "ticks": 0, "symbol": sym, "side": side,
                                            "entry": entry, "qty": fill["filled_qty"] or qty, "tp": tp, "sl": sl,
                                            "oid": oid, "pos_side": pos_side}
                                    log("MAKER FILL %s %s entry=%.6f" % (side, sym, entry))
                            finally:
                                k.flock.release()
                        except Exception as e: log("SNIPER skip %s: %s" % (sym, e))
            i += 1
        except Exception as e: log("loop %s: %s" % (type(e).__name__, e))
        time.sleep(INTERVAL)

def run_flask():
    try: from flask import Flask, jsonify
    except ImportError: return
    app = Flask(__name__)
    @app.route("/health")
    def health(): return jsonify({"ok": 1, "engine": "MAKER-SNIPER", "i": state["i"]})
    @app.route("/status")
    def status():
        with lock:
            return jsonify({"engine": "MAKER-SNIPER", "open": sum(1 for p in positions.values() if p.get("status")=="OPEN"),
                            "trades": len(journal), "on": state.get("on", True), "venue": VENUE})
    @app.route("/journal")
    def j():
        with lock: return jsonify(list(journal[:30]))
    @app.route("/logs")
    def l():
        with lock: return jsonify(list(logs[:60]))
    @app.route("/on", methods=["POST", "GET"])
    def on(): state["on"] = True; return jsonify({"on": True})
    @app.route("/off", methods=["POST", "GET"])
    def off(): state["on"] = False; return jsonify({"on": False})
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True, use_reloader=False)

if __name__ == "__main__":
    threading.Thread(target=loop, daemon=True).start()
    run_flask()
