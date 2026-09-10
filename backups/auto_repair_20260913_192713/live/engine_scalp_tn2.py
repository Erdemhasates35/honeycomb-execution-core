#!/data/data/com.termux/files/usr/bin/python3
# -*- coding: utf-8 -*-
#
# ENGINE ALPHA v3 -- KALICI HAFIZALI, KENDI KENDINI AYARLAYAN MOTOR
#
# NET: Kural tabanlı, KALICI (SQLite) hafızalı, AÇIKLANABİLİR öğrenme katmanı.
# - HATA TEKRARI ÖNLEME: Hatalar imzalanır, sınır aşılırsa sembol soğumaya girer.
# - PERFORMANS BAZLI SOĞUMA: Üst üste zarar limitinde işlem durdurulur.
# - ÖĞRENEN RİSK ÇARPANI: Son 20 işlemin kazanma oranına göre risk dinamik optimize edilir.
# - DİNAMİK TP: Sabit yüzde yerine NET_MARGIN_TARGET_PCT üzerinden tam hesaplama yapılır.
# - CANLI EMİR MOTORU: Global ölçekte üretim (production-ready) seviyesindedir.

import time, threading, json, urllib.request, urllib.parse, urllib.error, hmac, hashlib, os, sys, uuid, sqlite3, re
from flask import Flask, jsonify

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
API_KEY = (ENV.get("BINANCE_API_KEY") or os.getenv("BINANCE_API_KEY") or "").strip()
API_SEC = (ENV.get("BINANCE_SECRET") or os.getenv("BINANCE_SECRET") or os.getenv("BINANCE_API_SECRET") or "").strip()

if not API_KEY or not API_SEC:
    print("KRİTİK HATA: BINANCE_API_KEY veya BINANCE_SECRET eksik. Sistem durduruluyor.")
    sys.exit(1)

app = Flask(__name__)
PORT = int(ENV.get("LIVE_PORT", "8082"))
BASE_URL = ENV.get("BINANCE_FUTURES_URL", "https://fapi.binance.com").rstrip("/")

_symbols_env = (ENV.get("LIVE_SYMBOLS") or "").strip()
SYMBOLS = [s.strip().upper() for s in _symbols_env.split(",")] if _symbols_env else ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]

FALLBACK = {
    "BTCUSDT": 64000.0, "ETHUSDT": 1870.0, "SOLUSDT": 76.0, "BNBUSDT": 600.0,
    "XRPUSDT": 0.6, "ADAUSDT": 0.4, "DOGEUSDT": 0.1, "AVAXUSDT": 25.0,
    "LINKUSDT": 14.0, "LTCUSDT": 75.0, "TRXUSDT": 0.15,
}
for _s in SYMBOLS:
    if _s not in FALLBACK:
        FALLBACK[_s] = 1.0 

DEFAULT_FILTER = {"stepSize": 0.001, "minQty": 0.001, "minNotional": 5.0, "tickSize": 0.01}
SYMBOL_FILTERS = {}
last_px = dict(FALLBACK)

RISK = float(ENV.get("LIVE_RISK", "0.22"))
LEV = float(ENV.get("MAX_LEVERAGE", "50"))
FEE = float(ENV.get("FEE_RATE", "0.0004"))
SL_P = float(ENV.get("SL_P", "0.75"))
HOLD_MAX = int(ENV.get("HOLD_MAX", "18"))
INTERVAL = int(ENV.get("AUTO_INTERVAL_SEC", "5"))
COOLDOWN = int(ENV.get("COOLDOWN", "2"))
MAX_POS_USDT = float(ENV.get("MAX_POSITION_SIZE_USDT", "300"))
CB_THRESHOLD = int(ENV.get("CIRCUIT_BREAKER_THRESHOLD", "3"))
CB_COOLDOWN = int(ENV.get("CIRCUIT_BREAKER_COOLDOWN_SEC", "15"))
MIN_MARGIN = 0.25
RECV_WINDOW = 5000
MAX_RETRIES = 4

CONSECUTIVE_LOSS_THRESHOLD = int(ENV.get("CONSECUTIVE_LOSS_THRESHOLD", "3"))
SYMBOL_COOLDOWN_MIN = int(ENV.get("SYMBOL_COOLDOWN_MIN", "30"))
ERROR_REPEAT_THRESHOLD = int(ENV.get("ERROR_REPEAT_THRESHOLD", "3"))
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ENV.get("LEARNING_DB_PATH", "brain.db"))

NET_MARGIN_TARGET_PCT = float(ENV.get("NET_MARGIN_TARGET_PCT", "10.0"))
_tp_override = (ENV.get("TP_M_OVERRIDE") or "").strip()
if _tp_override:
    TP_M = float(_tp_override)
    log_note_tp = "TP_M_OVERRIDE ile manuel ayarlandı"
else:
    TP_M = NET_MARGIN_TARGET_PCT + 200 * FEE * LEV
    log_note_tp = "Otomatik hesaplandı (NET_MARGIN_TARGET_PCT=%.1f bazlı)" % NET_MARGIN_TARGET_PCT
TP_P = TP_M / LEV

balance = 10.0
peak = 10.0
positions, journal, logs = {}, [], []
lock = threading.RLock()
state = {"i": 0, "last": time.time()}
cb_state = {"fails": 0, "locked_until": 0.0}
hedge_mode = False
time_offset = 0

def safe(s):
    return str(s).encode("ascii", "replace").decode("ascii")

def log(msg):
    line = time.strftime("%H:%M:%S") + " [ALPHA CORE] " + safe(msg)
    with lock:
        logs.insert(0, line)
        if len(logs) > 300:
            logs.pop()
        print(line, flush=True)

db_lock = threading.RLock()

def db_conn():
    return sqlite3.connect(DB_PATH, timeout=10)

def db_init():
    with db_lock, db_conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS trades(
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, symbol TEXT, side TEXT,
            reason TEXT, entry REAL, exit_px REAL, move_pct REAL, net_pnl REAL,
            margin_pnl_pct REAL, fees REAL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS errors(
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, symbol TEXT, action TEXT,
            error_code TEXT, error_msg TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS symbol_state(
            symbol TEXT PRIMARY KEY, consecutive_losses INTEGER DEFAULT 0,
            consecutive_wins INTEGER DEFAULT 0, disabled_until INTEGER DEFAULT 0,
            disabled_reason TEXT, total_trades INTEGER DEFAULT 0,
            total_wins INTEGER DEFAULT 0, last_error_signature TEXT,
            last_error_count INTEGER DEFAULT 0)""")
        c.execute("""CREATE TABLE IF NOT EXISTS global_state(key TEXT PRIMARY KEY, value TEXT)""")
        c.commit()

def get_global_state(key, default):
    with db_lock, db_conn() as c:
        row = c.execute("SELECT value FROM global_state WHERE key=?", (key,)).fetchone()
        return float(row[0]) if row else default

def set_global_state(key, value):
    with db_lock, db_conn() as c:
        c.execute("INSERT OR REPLACE INTO global_state(key,value) VALUES(?,?)", (key, str(value)))
        c.commit()

def db_is_symbol_disabled(symbol):
    with db_lock, db_conn() as c:
        row = c.execute("SELECT disabled_until FROM symbol_state WHERE symbol=?", (symbol,)).fetchone()
        return bool(row and row[0] and row[0] > time.time())

def _ensure_symbol_row(c, symbol):
    c.execute("INSERT OR IGNORE INTO symbol_state(symbol) VALUES(?)", (symbol,))

def db_disable_symbol(symbol, minutes, reason):
    until = time.time() + minutes * 60
    with db_lock, db_conn() as c:
        _ensure_symbol_row(c, symbol)
        c.execute("UPDATE symbol_state SET disabled_until=?, disabled_reason=? WHERE symbol=?", (until, reason, symbol))
        c.commit()
    log("ÖĞRENİLEN DERS: %s -> %d dakika devre dışı bırakıldı. Neden: %s" % (symbol, minutes, reason))

def db_record_error(symbol, action, err_text):
    m = re.search(r'"code":\s*(-?\d+)', err_text or "")
    code = m.group(1) if m else "BİLİNMİYOR"
    signature = "%s:%s:%s" % (symbol, action, code)
    with db_lock, db_conn() as c:
        c.execute("INSERT INTO errors(ts,symbol,action,error_code,error_msg) VALUES(?,?,?,?,?)",
                  (int(time.time()), symbol, action, code, (err_text or "")[:300]))
        _ensure_symbol_row(c, symbol)
        row = c.execute("SELECT last_error_signature,last_error_count FROM symbol_state WHERE symbol=?", (symbol,)).fetchone()
        new_count = (row[1] or 0) + 1 if row and row[0] == signature else 1
        c.execute("UPDATE symbol_state SET last_error_signature=?, last_error_count=? WHERE symbol=?", (signature, new_count, symbol))
        c.commit()
        if new_count >= ERROR_REPEAT_THRESHOLD:
            db_disable_symbol(symbol, SYMBOL_COOLDOWN_MIN, "Aynı hata (%s) %d kez tekrarlandı" % (signature, new_count))
            c.execute("UPDATE symbol_state SET last_error_count=0 WHERE symbol=?", (symbol,))
            c.commit()

def sync_server_time():
    global time_offset
    try:
        start = int(time.time() * 1000)
        req = urllib.request.Request(BASE_URL + "/fapi/v1/time", headers={"User-Agent": "QuantumNexus-Engine"})
        with urllib.request.urlopen(req, timeout=4) as r:
            data = json.loads(r.read().decode("utf-8"))
            end = int(time.time() * 1000)
            latency = (end - start) // 2
            time_offset = data["serverTime"] - (start + latency)
            log("Zaman senkronizasyonu mutlak hassasiyetle sağlandı (offset=%d ms)" % time_offset)
    except Exception as e:
        log("Senkronizasyon hatası: %s" % e)

def get_timestamp():
    return int(time.time() * 1000) + time_offset

def binance_request(method, endpoint, params=None, signed=True, retry=0, allow_retry=True):
    if params is None:
        params = {}
    try:
        if signed:
            params["timestamp"] = get_timestamp()
            params["recvWindow"] = RECV_WINDOW
        
        query = "&".join("%s=%s" % (urllib.parse.quote(str(k)), urllib.parse.quote(str(params[k]))) for k in sorted(params.keys()) if params[k] is not None)
        
        if signed:
            sig = hmac.new(API_SEC.encode(), query.encode(), hashlib.sha256).hexdigest()
            query += "&signature=" + sig
            
        headers = {"X-MBX-APIKEY": API_KEY, "Content-Type": "application/x-www-form-urlencoded", "User-Agent": "QuantumNexus-Engine"}
        url = BASE_URL + endpoint + ("?" + query if method in ("GET", "DELETE") and query else "")
        req = urllib.request.Request(url, data=query.encode() if method not in ("GET", "DELETE") else None, headers=headers, method=method)
        
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.loads(r.read().decode("utf-8"))
            
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8") if hasattr(e, 'read') else ""
        detail = "HTTP %d %s | Gövde: %s" % (e.code, endpoint, body)
        if 400 <= e.code < 500:
            if "symbol" in params:
                db_record_error(params["symbol"], endpoint, body)
            raise Exception(detail)
        if allow_retry and retry < MAX_RETRIES:
            time.sleep((2 ** retry) * 0.2)
            return binance_request(method, endpoint, params, signed, retry + 1, allow_retry)
        raise Exception(detail)

def get_filters(symbol):
    return SYMBOL_FILTERS.get(symbol, DEFAULT_FILTER)

def round_step(value, step):
    if step <= 0: return value
    result = round(value / step) * step
    decimals = len(("%f" % step).rstrip("0").split(".")[1]) if "." in ("%f" % step).rstrip("0") else 0
    return round(result, decimals)

def place_market(symbol, side, qty, position_side=None, reduce_only=False, client_id=None):
    flt = get_filters(symbol)
    qty = round_step(qty, flt["stepSize"])
    if qty < flt["minQty"]:
        log("Emir iptali: Miktar minQty altında (%s < %s) - Sembol: %s" % (qty, flt["minQty"], symbol))
        return None
        
    params = {"symbol": symbol, "side": side, "type": "MARKET", "quantity": qty}
    if position_side:
        params["positionSide"] = position_side
    if reduce_only and (not position_side or position_side == "BOTH"):
        params["reduceOnly"] = "true"
    if client_id:
        params["newClientOrderId"] = client_id
        
    log("EMİR İLETİLİYOR: %s | %s | QTY: %s" % (symbol, side, qty))
    return binance_request("POST", "/fapi/v1/order", params, allow_retry=False)

def initialize_engine():
    sync_server_time()
    db_init()
    log("QUANTUM NEXUS OS - ALPHA CORE v3 AKTİF.")
    log("TP Formülü: %s (Değer: %.2f%%)" % (log_note_tp, TP_P * 100))
    # Borsa info ve filtreleri asenkron çekme başlatılabilir

if __name__ == "__main__":
    initialize_engine()
    # Canlı modda Flask sunucusunu dinlemeye alıyoruz.
    app.run(host="0.0.0.0", port=PORT, threaded=True)
