#!/data/data/com.termux/files/usr/bin/python3
# -*- coding: utf-8 -*-
#
# ENGINE ALPHA v3 -- KALICI HAFIZALI, KENDI KENDINI AYARLAYAN MOTOR
#
# NET: Bu bir "yapay zeka" (sinir agi) degil -- kural tabanli, KALICI
# (SQLite) hafizali, ACIKLANABILIR bir ogrenme katmanidir. Ne yapiyor:
#   1. HATA TEKRARINI ONLEME: Her API hatasi (code+mesaj) imzalanip
#      kaydedilir. Ayni imza ust uste ERROR_REPEAT_THRESHOLD kez
#      tekrarlarsa, o sembol SYMBOL_COOLDOWN_MIN dakika otomatik
#      devre disi birakilir -- motor "ayni hatayi" korculesine
#      tekrar tekrar denemez.
#   2. PERFORMANS BAZLI SOGUMA: Bir sembolde ust uste
#      CONSECUTIVE_LOSS_THRESHOLD zarar olursa, o sembol de soguma
#      suresine girer.
#   3. OGRENEN RISK CARPANI: Son 20 islemin kazanma orani dusukse
#      risk carpani kademeli azalir (min 0.5x), yukselirse kademeli
#      artar (max 1.0x -- orijinal riski asla asmaz). Bu carpan
#      brain.db icinde KALICIDIR, yeniden baslatmada sifirlanmaz.
#   4. KAR HEDEFI FORMULLE HESAPLANIR: TP artik sabit bir yuzde
#      degil; NET_MARGIN_TARGET_PCT (ucret dahil net hedef) ve
#      gercek FEE_RATE/kaldiractan otomatik turetilir.
#   5. TOKEN CESITLENDIRME: LIVE_SYMBOLS ile coklu sembol, her biri
#      bagimsiz soguma/istatistik takibi ile.
#
# v2'den korunan duzeltmeler: HTTPError govdesi loglama, yazma
# islemlerinde kor retry yok (idempotent clientOrderId), exchangeInfo
# tabanli dinamik precision, closePosition=true KULLANILMIYOR (daha
# once -4136 ile reddedildigi kanitlandi), baslangic mutabakati.

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
    print("KRITIK: BINANCE_API_KEY / BINANCE_SECRET eksik")
    sys.exit(1)

app = Flask(__name__)
PORT = int(ENV.get("LIVE_PORT", "8082"))
BASE_URL = ENV.get("BINANCE_FUTURES_URL", "https://fapi.binance.com").rstrip("/")

# ---- Coklu sembol / token cesitlendirme ----
_symbols_env = (ENV.get("LIVE_SYMBOLS") or "").strip()
if _symbols_env:
    SYMBOLS = [s.strip().upper() for s in _symbols_env.split(",") if s.strip()]
else:
    SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]

# Bu degerler SADECE canli fiyat cekimi basarisiz olursa kullanilan
# ACIL YEDEKTIR -- guncel/gercek fiyat degildir, karar vermede
# neredeyse hic rol oynamaz (fetch_px her tick gercek fiyati ceker).
FALLBACK = {
    "BTCUSDT": 64000.0, "ETHUSDT": 1870.0, "SOLUSDT": 76.0, "BNBUSDT": 600.0,
    "XRPUSDT": 0.6, "ADAUSDT": 0.4, "DOGEUSDT": 0.1, "AVAXUSDT": 25.0,
    "LINKUSDT": 14.0, "LTCUSDT": 75.0, "TRXUSDT": 0.15,
}
for _s in SYMBOLS:
    if _s not in FALLBACK:
        FALLBACK[_s] = 1.0  # bilinmeyen sembol icin notr yedek

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

# ---- Ogrenme / hafiza ayarlari ----
CONSECUTIVE_LOSS_THRESHOLD = int(ENV.get("CONSECUTIVE_LOSS_THRESHOLD", "3"))
SYMBOL_COOLDOWN_MIN = int(ENV.get("SYMBOL_COOLDOWN_MIN", "30"))
ERROR_REPEAT_THRESHOLD = int(ENV.get("ERROR_REPEAT_THRESHOLD", "3"))
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        ENV.get("LEARNING_DB_PATH", "brain.db"))

# ---- Kar hedefi: formulle turetilen TP (sabit yuzde degil) ----
NET_MARGIN_TARGET_PCT = float(ENV.get("NET_MARGIN_TARGET_PCT", "10.0"))
_tp_override = (ENV.get("TP_M_OVERRIDE") or "").strip()
if _tp_override:
    TP_M = float(_tp_override)
    log_note_tp = "TP_M_OVERRIDE ile manuel ayarlandi"
else:
    # Turetme: net_marjin% = (TP_P/100 - 2*FEE) * LEV * 100
    # => TP_M = TP_P*LEV = NET_MARGIN_TARGET_PCT + 200*FEE*LEV
    TP_M = NET_MARGIN_TARGET_PCT + 200 * FEE * LEV
    log_note_tp = "otomatik hesaplandi (NET_MARGIN_TARGET_PCT=%.1f bazli)" % NET_MARGIN_TARGET_PCT
TP_P = TP_M / LEV

balance = 10.0
peak = 10.0
positions, journal, logs = {}, [], []
lock = threading.RLock()
state = {"i": 0, "last": time.time()}
cb_state = {"fails": 0, "locked_until": 0.0}
hedge_mode = False
time_offset = 0
skip_log_counter = 0

def safe(s):
    return str(s).encode("ascii", "replace").decode("ascii")

def log(msg):
    line = time.strftime("%H:%M:%S") + " [ALPHA] " + safe(msg)
    with lock:
        logs.insert(0, line)
        if len(logs) > 300:
            logs.pop()
    print(line, flush=True)

# =====================================================================
# OGRENME / HAFIZA KATMANI (SQLite, kalici -- yeniden baslatmada silinmez)
# =====================================================================
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
        c.execute("""CREATE TABLE IF NOT EXISTS global_state(
            key TEXT PRIMARY KEY, value TEXT)""")
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
        c.execute("UPDATE symbol_state SET disabled_until=?, disabled_reason=? WHERE symbol=?",
                   (until, reason, symbol))
        c.commit()
    log("DERS CIKARILDI: %s -> %d dakika devre disi (%s)" % (symbol, minutes, reason))

def db_record_error(symbol, action, err_text):
    m = re.search(r'"code":\s*(-?\d+)', err_text or "")
    code = m.group(1) if m else "BILINMIYOR"
    signature = "%s:%s:%s" % (symbol, action, code)
    with db_lock, db_conn() as c:
        c.execute("INSERT INTO errors(ts,symbol,action,error_code,error_msg) VALUES(?,?,?,?,?)",
                   (int(time.time()), symbol, action, code, (err_text or "")[:300]))
        _ensure_symbol_row(c, symbol)
        row = c.execute("SELECT last_error_signature,last_error_count FROM symbol_state WHERE symbol=?",
                         (symbol,)).fetchone()
        if row and row[0] == signature:
            new_count = (row[1] or 0) + 1
        else:
            new_count = 1
        c.execute("UPDATE symbol_state SET last_error_signature=?, last_error_count=? WHERE symbol=?",
                   (signature, new_count, symbol))
        c.commit()
    if new_count >= ERROR_REPEAT_THRESHOLD:
        db_disable_symbol(symbol, SYMBOL_COOLDOWN_MIN,
                           "ayni hata (%s) %d kez tekrarladi" % (signature, new_count))
        with db_lock, db_conn() as c:
            c.execute("UPDATE symbol_state SET last_error_count=0 WHERE symbol=?", (symbol,))
            c.commit()

def db_record_trade(rec):
    with db_lock, db_conn() as c:
        c.execute("""INSERT INTO trades(ts,symbol,side,reason,entry,exit_px,move_pct,net_pnl,
                     margin_pnl_pct,fees) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                   (int(time.time()), rec["symbol"], rec["side"], rec["reason"], rec["entry"],
                    rec["exit"], rec["move_pct"], rec["net_pnl"], rec["margin_pnl_pct"], rec["total_fees"]))
        _ensure_symbol_row(c, rec["symbol"])
        is_win = rec["net_pnl"] > 0
        row = c.execute("SELECT consecutive_losses,consecutive_wins,total_trades,total_wins FROM symbol_state WHERE symbol=?",
                         (rec["symbol"],)).fetchone()
        cl, cw, tt, tw = row if row else (0, 0, 0, 0)
        tt = (tt or 0) + 1
        if is_win:
            tw = (tw or 0) + 1
            cw = (cw or 0) + 1
            cl = 0
        else:
            cl = (cl or 0) + 1
            cw = 0
        c.execute("""UPDATE symbol_state SET consecutive_losses=?, consecutive_wins=?,
                     total_trades=?, total_wins=? WHERE symbol=?""",
                   (cl, cw, tt, tw, rec["symbol"]))
        c.commit()
    if cl >= CONSECUTIVE_LOSS_THRESHOLD:
        db_disable_symbol(rec["symbol"], SYMBOL_COOLDOWN_MIN,
                           "ust uste %d zarar (performans bazli soguma)" % cl)
        with db_lock, db_conn() as c:
            c.execute("UPDATE symbol_state SET consecutive_losses=0 WHERE symbol=?", (rec["symbol"],))
            c.commit()
    db_recompute_learned_risk()

def db_recompute_learned_risk():
    with db_lock, db_conn() as c:
        rows = c.execute("SELECT net_pnl FROM trades ORDER BY id DESC LIMIT 20").fetchall()
    if len(rows) < 5:
        return
    wins = sum(1 for r in rows if r[0] > 0)
    win_rate = wins / len(rows)
    current = get_global_state("learned_risk_multiplier", 1.0)
    new_mult = current
    if win_rate < 0.35:
        new_mult = max(0.5, current * 0.9)
    elif win_rate > 0.55:
        new_mult = min(1.0, current * 1.05)
    if abs(new_mult - current) > 0.001:
        set_global_state("learned_risk_multiplier", new_mult)
        log("OGRENME: son %d islem kazanma orani %%%.0f -> risk carpani %.2f -> %.2f" % (
            len(rows), win_rate * 100, current, new_mult))

def get_active_symbols():
    return [s for s in SYMBOLS if not db_is_symbol_disabled(s)]

db_init()

# =====================================================================
# BINANCE ISTEK KATMANI (v2'den korunan)
# =====================================================================

def sync_server_time():
    global time_offset
    try:
        start = int(time.time() * 1000)
        req = urllib.request.Request(BASE_URL + "/fapi/v1/time", headers={"User-Agent": "hc-alpha"})
        with urllib.request.urlopen(req, timeout=4) as r:
            data = json.loads(r.read().decode("utf-8"))
        end = int(time.time() * 1000)
        latency = (end - start) // 2
        time_offset = data["serverTime"] - (start + latency)
        log("Zaman senkronu tamamlandi (offset=%d ms)" % time_offset)
    except Exception as e:
        log("Zaman senkronu basarisiz: %s" % e)

def get_timestamp():
    return int(time.time() * 1000) + time_offset

def binance_request(method, endpoint, params=None, signed=True, retry=0, allow_retry=True):
    if params is None:
        params = {}
    try:
        if signed:
            params["timestamp"] = get_timestamp()
            params["recvWindow"] = RECV_WINDOW
        keys = sorted(params.keys())
        query = "&".join(
            "%s=%s" % (urllib.parse.quote(str(k)), urllib.parse.quote(str(params[k])))
            for k in keys if params[k] is not None
        )
        if signed:
            sig = hmac.new(API_SEC.encode(), query.encode(), hashlib.sha256).hexdigest()
            query = query + "&signature=" + sig
        headers = {
            "X-MBX-APIKEY": API_KEY,
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "hc-alpha"
        }
        if method in ("GET", "DELETE"):
            url = BASE_URL + endpoint + ("?" + query if query else "")
            req = urllib.request.Request(url, headers=headers, method=method)
        else:
            url = BASE_URL + endpoint
            req = urllib.request.Request(url, data=query.encode(), headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.loads(r.read().decode("utf-8"))

    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8")
        except Exception:
            pass
        detail = "HTTP %d %s | body=%s" % (e.code, endpoint, body if body else "(bos)")
        if 400 <= e.code < 500:
            raise Exception(detail)
        if allow_retry and retry < MAX_RETRIES:
            delay = (2 ** retry) * 0.2 + (time.time() % 0.1)
            time.sleep(delay)
            return binance_request(method, endpoint, params, signed, retry + 1, allow_retry)
        raise Exception(detail)

    except Exception as e:
        if allow_retry and retry < MAX_RETRIES:
            delay = (2 ** retry) * 0.2 + (time.time() % 0.1)
            time.sleep(delay)
            return binance_request(method, endpoint, params, signed, retry + 1, allow_retry)
        raise e

def load_exchange_info():
    try:
        res = binance_request("GET", "/fapi/v1/exchangeInfo", signed=False, allow_retry=True)
        for s in res.get("symbols", []):
            sym = s["symbol"]
            if sym not in SYMBOLS:
                continue
            f = dict(DEFAULT_FILTER)
            for flt in s.get("filters", []):
                ft = flt.get("filterType")
                if ft == "LOT_SIZE":
                    f["stepSize"] = float(flt["stepSize"])
                    f["minQty"] = float(flt["minQty"])
                elif ft in ("MIN_NOTIONAL", "NOTIONAL"):
                    f["minNotional"] = float(flt.get("notional", flt.get("minNotional", f["minNotional"])))
                elif ft == "PRICE_FILTER":
                    f["tickSize"] = float(flt["tickSize"])
            SYMBOL_FILTERS[sym] = f
            log("Filtre yuklendi %s: step=%s minQty=%s minNotional=%s" % (
                sym, f["stepSize"], f["minQty"], f["minNotional"]))
    except Exception as e:
        log("exchangeInfo alinamadi, varsayilan filtreler kullanilacak: %s" % e)

def round_step(value, step):
    if step <= 0:
        return value
    steps = round(value / step)
    result = steps * step
    decimals = 0
    s = ("%f" % step).rstrip("0")
    if "." in s:
        decimals = len(s.split(".")[1])
    return round(result, decimals)

def get_filters(symbol):
    return SYMBOL_FILTERS.get(symbol, DEFAULT_FILTER)

def get_balance_usdt():
    try:
        res = binance_request("GET", "/fapi/v2/balance")
        for a in res:
            if a.get("asset") == "USDT":
                return float(a.get("balance", 0))
    except Exception as e:
        log("Bakiye okunamadi: %s" % e)
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
        log("Pozisyon bilgisi alinamadi: %s" % e)
    return 0.0

def set_leverage(symbol, lev):
    try:
        binance_request("POST", "/fapi/v1/leverage", {"symbol": symbol, "leverage": int(lev)})
    except Exception as e:
        log("Kaldirac ayarlanamadi: %s" % e)

def new_client_order_id(prefix):
    return "%s-%d-%s" % (prefix, int(time.time() * 1000), uuid.uuid4().hex[:8])

def place_market(symbol, side, qty, position_side=None, reduce_only=False, client_id=None):
    params = {"symbol": symbol, "side": side, "type": "MARKET", "quantity": qty}
    if position_side:
        params["positionSide"] = position_side
    if reduce_only and (not position_side or position_side == "BOTH"):
        params["reduceOnly"] = "true"
    if client_id:
        params["newClientOrderId"] = client_id
    return binance_request("POST", "/fapi/v1/order", params, allow_retry=False)

def fetch_px(symbol):
    try:
        url = "https://fapi.binance.com/fapi/v1/ticker/price?symbol=" + symbol
        req = urllib.request.Request(url, headers={"Connection": "close", "User-Agent": "hc"})
        with urllib.request.urlopen(req, timeout=2) as r:
            px = float(json.loads(r.read().decode("utf-8"))["price"])
            last_px[symbol] = px
            return px, "canli"
    except Exception:
        return last_px.get(symbol, FALLBACK.get(symbol, 1.0)), "yedek"

def fetch_klines(symbol, limit=50):
    try:
        url = "https://fapi.binance.com/fapi/v1/klines?symbol=%s&interval=1m&limit=%d" % (symbol, limit)
        req = urllib.request.Request(url, headers={"User-Agent": "hc"})
        with urllib.request.urlopen(req, timeout=4) as r:
            data = json.loads(r.read().decode("utf-8"))
        closes = [float(x[4]) for x in data]
        return closes
    except Exception as e:
        log("Kline alinamadi (%s): %s" % (symbol, e))
        return []

def ema(values, period):
    if len(values) < period:
        return None
    k = 2.0 / (period + 1)
    ema_val = sum(values[:period]) / period
    for v in values[period:]:
        ema_val = v * k + ema_val * (1 - k)
    return ema_val

def rsi(values, period=14):
    if len(values) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(values)):
        diff = values[i] - values[i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))

def get_signal(symbol):
    closes = fetch_klines(symbol, 50)
    if len(closes) < 25:
        return None, "veri yetersiz"
    e9 = ema(closes, 9)
    e21 = ema(closes, 21)
    r = rsi(closes, 14)
    if e9 is None or e21 is None or r is None:
        return None, "indikator hesaplanamadi"
    if e9 > e21 and 42 <= r <= 68:
        return "LONG", "EMA9>EMA21 + RSI=%.1f" % r
    if e9 < e21 and 32 <= r <= 58:
        return "SHORT", "EMA9<EMA21 + RSI=%.1f" % r
    return None, "filtre uyusmadi (EMA9=%.2f EMA21=%.2f RSI=%.1f)" % (e9, e21, r)

def cb_check():
    now = time.time()
    if cb_state["locked_until"] > now:
        return False
    if cb_state["fails"] >= CB_THRESHOLD:
        cb_state["locked_until"] = now + CB_COOLDOWN
        cb_state["fails"] = 0
        log("DEVRE KESICI: %d saniye bekleniyor" % CB_COOLDOWN)
        return False
    return True

def cb_hit():
    cb_state["fails"] += 1

def cb_reset():
    cb_state["fails"] = 0

def open_pos(symbol, side, px, src, reason):
    global balance
    with lock:
        if any(p.get("status") == "OPEN" for p in positions.values()):
            return
        if not cb_check():
            return
        if db_is_symbol_disabled(symbol):
            return  # ogrenme katmani bu sembolu soguma sürecine almis

        real = get_balance_usdt()
        if real > 0:
            balance = real

        learned_mult = get_global_state("learned_risk_multiplier", 1.0)
        margin = balance * RISK * learned_mult
        if margin < MIN_MARGIN:
            global skip_log_counter
            skip_log_counter += 1
            if skip_log_counter % 8 == 1:
                log("Yetersiz margin (%.2f USDT, ogrenilen carpan=%.2f), islem acilmadi" % (margin, learned_mult))
            return

        notional = min(margin * LEV, MAX_POS_USDT)
        margin = notional / LEV

        f = get_filters(symbol)
        qty = round_step(notional / px, f["stepSize"])
        if qty < f["minQty"] or qty * px < f["minNotional"]:
            log("Filtre altinda (qty=%.6f notional=%.2f < min=%.2f), islem acilmadi" % (
                qty, qty * px, f["minNotional"]))
            return

        set_leverage(symbol, int(LEV))
        binance_side = "BUY" if side == "LONG" else "SELL"
        pos_side = side if hedge_mode else None
        cid = new_client_order_id("open")

        try:
            res = place_market(symbol, binance_side, qty, pos_side, client_id=cid)
            oid = res.get("orderId", 0)
            exec_px = float(res.get("avgPrice") or px)
            if exec_px <= 0:
                exec_px = px
            cb_reset()
            log("Emir kabul edildi | Emir No: %s | ClientID: %s | Fiyat: %.4f | Miktar: %s | Yon: %s" % (
                oid, cid, exec_px, qty, side))
        except Exception as e:
            cb_hit()
            db_record_error(symbol, "open", str(e))
            log("Acilis basarisiz: %s" % e)
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
            "binance_id": oid, "pos_side": pos_side, "signal": reason
        }
        log(
            "POZISYON ACILDI | %s %s | Giris: %.4f | Margin: %.2f (risk carpani %.2f) | Notional: %.2f | "
            "Kaldirac: %.0fx | TP: %.4f (+%.2f%%, hedef net %.0f%%) | SL: %.4f | Acilis ucreti: %.4f | "
            "Sinyal: %s | Kalan bakiye: %.2f" % (
                side, symbol, px, margin, learned_mult, notional, LEV, tp, TP_P,
                NET_MARGIN_TARGET_PCT, sl, open_fee, reason, balance)
        )

def close_pos(pos, px, reason, src):
    global balance, peak
    pos_side = pos.get("pos_side")
    real_qty = get_position_amt(pos["symbol"], pos["side"])
    if real_qty <= 0:
        log("Kapatma iptal: Borsada acik pozisyon yok")
        with lock:
            if pos["id"] in positions:
                del positions[pos["id"]]
        return

    f = get_filters(pos["symbol"])
    qty = min(pos["qty"], real_qty)
    qty = round_step(qty, f["stepSize"])
    if qty <= 0:
        log("Kapatma iptal: hesaplanan miktar sifir")
        return

    close_side = "SELL" if pos["side"] == "LONG" else "BUY"
    cid = new_client_order_id("close")

    try:
        res = place_market(pos["symbol"], close_side, qty,
                            position_side=pos_side, reduce_only=True, client_id=cid)
        px = float(res.get("avgPrice") or px)
        cb_reset()
        log("Kapatma emri kabul edildi | Emir No: %s | Cikis: %.4f" % (res.get("orderId"), px))
    except Exception as e:
        cb_hit()
        db_record_error(pos["symbol"], "close", str(e))
        log("Kapatma basarisiz — pozisyon HALA ACIK OLABILIR, manuel kontrol gerekli: %s" % e)
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

    sonuc = "KAR" if net > 0 else "ZARAR"
    log(
        "POZISYON KAPANDI | %s %s | Sebep: %s | Giris: %.4f -> Cikis: %.4f | Hareket: %.3f%% | "
        "Toplam ucret: %.4f USDT | Net PnL: %.4f USDT (%s) | Margin: %.1f%% | "
        "Yeni bakiye: %.2f | DD: %.1f%%" % (
            pos["side"], pos["symbol"], reason, pos["entry"], px, move, fees, net, sonuc, m_pct, bal, dd)
    )
    db_record_trade(rec)

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

def reconcile_on_start():
    try:
        for sym in SYMBOLS:
            for side in ("LONG", "SHORT"):
                amt = get_position_amt(sym, side)
                if amt > 0:
                    log("UYARI: Baslangicta borsada takip edilmeyen ACIK pozisyon bulundu: %s %s miktar=%.6f — manuel kontrol edin" % (sym, side, amt))
    except Exception as e:
        log("Baslangic mutabakati basarisiz: %s" % e)

def loop():
    global hedge_mode, balance, peak
    sync_server_time()
    load_exchange_info()
    try:
        hedge_mode = get_position_mode()
        log("Pozisyon modu: %s" % ("HEDGE" if hedge_mode else "ONE-WAY"))
    except Exception as e:
        log("Pozisyon modu okunamadi: %s" % e)

    reconcile_on_start()

    real = get_balance_usdt()
    if real > 0:
        balance = real
        peak = real

    log(
        "OGRENEN MOTOR BASLADI (v3) | Bakiye: %.2f | Risk: %.0f%% | Kaldirac: %.0fx | "
        "TP: %.2f%% (%s) | SL: %.2f%% | Hold: %d | Semboller: %s | Filtre: EMA9/21 + RSI" % (
            balance, RISK * 100, LEV, TP_P, log_note_tp, SL_P, HOLD_MAX, ",".join(SYMBOLS))
    )

    i = 0
    idle = 0
    last_sync = time.time()
    while True:
        try:
            if time.time() - last_sync > 1800:
                sync_server_time()
                last_sync = time.time()

            state["i"] = i
            state["last"] = time.time()

            with lock:
                opens = [p for p in positions.values() if p.get("status") == "OPEN"]

            if opens:
                pos = opens[0]
                pos["ticks"] += 1
                px, src = fetch_px(pos["symbol"])
                reason = check_exit(pos, px)

                if pos["side"] == "LONG":
                    unreal = (px - pos["entry"]) * pos["qty"]
                else:
                    unreal = (pos["entry"] - px) * pos["qty"]
                unreal_pct = unreal / pos["margin"] * 100 if pos["margin"] else 0

                if reason:
                    close_pos(pos, px, reason, src)
                    idle = COOLDOWN
                elif pos["ticks"] >= HOLD_MAX:
                    close_pos(pos, px, "SURE DOLDU", src)
                    idle = COOLDOWN
                else:
                    dtp = abs(px - pos["tp"]) / pos["entry"] * 100
                    dsl = abs(px - pos["sl"]) / pos["entry"] * 100
                    durum = "KARDA" if unreal > 0 else "ZARARDA"
                    log(
                        "TUTULUYOR | %s %s | Tick: %d/%d | Fiyat: %.4f | "
                        "Anlik PnL: %.4f (%.1f%%) %s | TP uzak: %.3f%% | SL uzak: %.3f%%" % (
                            pos["side"], pos["symbol"], pos["ticks"], HOLD_MAX, px,
                            unreal, unreal_pct, durum, dtp, dsl)
                    )
            else:
                if idle > 0:
                    idle -= 1
                else:
                    active = get_active_symbols()
                    if not active:
                        if i % 12 == 0:
                            log("Tum semboller soguma surecinde, bekleniyor")
                    else:
                        sym = active[i % len(active)]
                        signal, detail = get_signal(sym)
                        if signal:
                            px, src = fetch_px(sym)
                            open_pos(sym, signal, px, src, detail)
                        else:
                            if i % 6 == 0:
                                log("Filtre: %s -> %s" % (sym, detail))
            i += 1
        except Exception as e:
            log("Dongu hatasi: %s: %s" % (type(e).__name__, e))
        time.sleep(INTERVAL)

@app.route("/health")
def health():
    return jsonify({"ok": 1, "i": state["i"], "age": round(time.time() - state["last"], 1), "engine": "alpha-v3-ogrenen"})

@app.route("/status")
def status():
    with lock:
        n = sum(1 for p in positions.values() if p.get("status") == "OPEN")
        return jsonify({"balance": round(balance, 2), "open": n, "lev": LEV, "trades": len(journal), "mode": "LIVE-V3"})

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
        "tp_pct": round(TP_P, 4),
        "net_margin_target_pct": NET_MARGIN_TARGET_PCT,
        "learned_risk_multiplier": get_global_state("learned_risk_multiplier", 1.0),
        "mode": "LIVE-V3"
    })

@app.route("/lessons")
def lessons_ep():
    with db_lock, db_conn() as c:
        symbols = c.execute("""SELECT symbol,consecutive_losses,consecutive_wins,disabled_until,
                                disabled_reason,total_trades,total_wins,last_error_signature,
                                last_error_count FROM symbol_state""").fetchall()
        errors = c.execute("""SELECT ts,symbol,action,error_code,error_msg FROM errors
                               ORDER BY id DESC LIMIT 20""").fetchall()
    now = time.time()
    return jsonify({
        "learned_risk_multiplier": get_global_state("learned_risk_multiplier", 1.0),
        "symbols": [
            {
                "symbol": s[0], "consecutive_losses": s[1], "consecutive_wins": s[2],
                "disabled": bool(s[3] and s[3] > now),
                "disabled_remaining_min": round((s[3] - now) / 60, 1) if s[3] and s[3] > now else 0,
                "disabled_reason": s[4],
                "total_trades": s[5], "total_wins": s[6],
                "win_rate": round(100.0 * s[6] / s[5], 1) if s[5] else None,
                "last_error_signature": s[7], "last_error_count": s[8],
            } for s in symbols
        ],
        "recent_errors": [
            {"ts": e[0], "symbol": e[1], "action": e[2], "code": e[3], "msg": e[4]} for e in errors
        ]
    })

if __name__ == "__main__":
    threading.Thread(target=loop, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True, use_reloader=False)
