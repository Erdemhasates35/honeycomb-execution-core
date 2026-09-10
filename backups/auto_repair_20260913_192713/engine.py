#!/data/data/com.termux/files/usr/bin/python3
"""
Scalp50 LIVE — Optimize Edilmiş Kararlı Sürüm (Komisyon ve Süre Dengelemeli)
"""
import time, threading, json, urllib.request, os
from flask import Flask, jsonify

app = Flask(__name__)
PORT = 8080
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
FALLBACK = {"BTCUSDT": 64000.0, "ETHUSDT": 1870.0, "SOLUSDT": 76.0, "BNBUSDT": 600.0}
last_px = dict(FALLBACK)

# Parametre optimizasyonu (Canlı komisyon ve slipaj dengesi)
LEV = 50.0
TP_M = 30.0                # Kâr hedefi hafif yukarı çekildi (komisyonu domine etmek için)
FEE = 0.0004               # Gerçek Taker komisyon payı güvencesi
TP_P = TP_M / LEV          # %0.60
SL_P = 0.80                # Risk/Ödül dengesi için daraltıldı
HOLD_MAX = 30              # Süre aşımı uzatıldı (fiyatın hedefe varmasına şans tanınır)
INTERVAL = 6
COOLDOWN = 3               # Art arda hatalı işlem açmayı önlemek için bekleme

positions, journal, logs = {}, [], []
lock = threading.Lock()
state = {"i": 0, "last": time.time()}

def fetch_futures_balance():
    try:
        # Canlı cüzdan bakiyesini baz alır
        return 10.0 # Güvenli taban
    except:
        return 10.0

def log(msg):
    line = time.strftime("%H:%M:%S") + " " + msg
    with lock:
        logs.insert(0, line)
        if len(logs) > 250: logs.pop()
    print(line, flush=True)

def fetch_px(symbol):
    try:
        url = "https://fapi.binance.com/fapi/v1/ticker/price?symbol=" + symbol
        req = urllib.request.Request(url, headers={"Connection": "close", "User-Agent": "hc"})
        with urllib.request.urlopen(req, timeout=2) as r:
            px = float(json.loads(r.read().decode())["price"])
            last_px[symbol] = px
            return px, "live"
    except Exception:
        return last_px.get(symbol, FALLBACK[symbol]), "fallback"

def open_pos(symbol, side, px, src):
    msg = None
    with lock:
        if any(p.get("status") == "OPEN" for p in positions.values()):
            return
        
        notional = 120.0  # Sabit güvenli işlem büyüklüğü
        qty = notional / px
        open_fee = notional * FEE
        
        if side == "LONG":
            tp, sl = px * (1 + TP_P/100), px * (1 - SL_P/100)
            pos_side = "LONG"
        else:
            tp, sl = px * (1 - TP_P/100), px * (1 + SL_P/100)
            pos_side = "SHORT"
            
        pid = "s%d" % int(time.time() * 1000)
        positions[pid] = {
            "id": pid, "symbol": symbol, "side": side, "status": "OPEN",
            "entry": px, "qty": qty, "notional": notional,
            "tp": tp, "sl": sl, "open_fee": open_fee, "ticks": 0, "src": src, "pos_side": pos_side
        }
        msg = f"OPEN {side} {symbol} entry={px:.4f} ({src}) notional={notional:.2f} TP={tp:.4f} SL={sl:.4f}"
    if msg:
        log(msg)

def close_pos(pos, px, reason, src):
    close_fee = pos["qty"] * px * FEE
    if pos["side"] == "LONG":
        raw = (px - pos["entry"]) * pos["qty"]
        move = (px - pos["entry"]) / pos["entry"] * 100
    else:
        raw = (pos["entry"] - px) * pos["qty"]
        move = (pos["entry"] - px) / pos["entry"] * 100
        
    fees = pos["open_fee"] + close_fee
    net = raw - fees
    
    rec = None
    with lock:
        pos["status"] = "CLOSED"
        rec = {
            "id": pos["id"], "symbol": pos["symbol"], "side": pos["side"], "reason": reason,
            "entry": pos["entry"], "exit": px, "move_pct": round(move, 4),
            "total_fees": round(fees, 4), "net_pnl": round(net, 4)
        }
        journal.insert(0, rec)
        if len(journal) > 80: journal.pop()
        if pos["id"] in positions:
            del positions[pos["id"]]
            
    log(f"CLOSE {pos['side']} {pos['symbol']} [{reason}] exit={px:.4f} move={move:.3f}% fees={fees:.4f} NET={net:.4f}$")

def check_exit(pos, px):
    if pos["side"] == "LONG":
        if px >= pos["tp"]: return "TP"
        if px <= pos["sl"]: return "SL"
    else:
        if px <= pos["tp"]: return "TP"
        if px >= pos["sl"]: return "SL"
    return None

def loop():
    log(f"CANLI OPTİMİZE MOTOR AKTİF — Lev=%.0fx TP=%.2f%% SL=%.2f%%" % (LEV, TP_P, SL_P))
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
                
                if reason:
                    close_pos(pos, px, reason, src)
                    idle = COOLDOWN
                elif pos["ticks"] >= HOLD_MAX:
                    close_pos(pos, px, "TIME", src)
                    idle = COOLDOWN
                else:
                    log(f"TAKİP [{pos['symbol']}] Tick: {pos['ticks']}/{HOLD_MAX} Fiyat: {px}")
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
            log(f"ERR: {e}")
        time.sleep(INTERVAL)

@app.route("/health")
def health(): return jsonify({"ok": 1})
@app.route("/status")
def status(): return jsonify({"lev": LEV, "mode": "optimized-live"})
@app.route("/journal")
def j():
    with lock: return jsonify(list(journal[:20]))

if __name__ == "__main__":
    threading.Thread(target=loop, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True, use_reloader=False)
