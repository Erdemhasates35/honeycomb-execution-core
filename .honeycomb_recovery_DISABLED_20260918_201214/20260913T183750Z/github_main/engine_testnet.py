#!/data/data/com.termux/files/usr/bin/python3
# -*- coding: utf-8 -*-
#
# ENGINE TESTNET v2 — GERCEK Binance Futures Testnet baglantisi.
#
# ONCEKI SURUMDEN FARK (kritik):
#   Eski engine_testnet.py sadece herkese acik /ticker/price endpoint'ini
#   okuyup pozisyonlari BELLEKTE simule ediyordu -- hicbir imzali istek,
#   hicbir gercek emir, hicbir gercek fill YOKTU. Bu yuzden sonuclar
#   gercek piyasa mikroyapisini (slippage, emir reddi, minNotional,
#   precision) hic yansitmiyordu.
#
#   Bu surum, engine_alpha.py (canli motor) ile AYNI imzali istek
#   altyapisini kullanir (HMAC-SHA256, timestamp, recvWindow) ama
#   BASE_URL testnet'e isaret eder. Yani:
#     - Gercek emir gonderiliyor (testnet borsasinda, gercek para degil)
#     - Gercek fill fiyati aliniyor (avgPrice borsadan donuyor)
#     - Gercek 400/-1111/-4164 gibi hatalar gorunur oluyor
#     - Gercek exchangeInfo (stepSize/minNotional) uygulaniyor
#   Boylece canliya gecmeden ONCE motorun borsa kurallariyla nasil
#   etkilesecegini gercekten test edebiliyorsun.
#
# NOT: Testnet bakiyesi Binance'in verdigi SAHTE USDT'dir. TL_USD_RATE
# ve TESTNET_REF_CAPITAL_TL yalnizca senin loglari "1000 TL karsiligi
# ne durumdayim" diye takip edebilmen icin bir GORUNTULEME katmanidir --
# gercek bir para transferi veya kur islemi yapmaz.

import time, threading, json, urllib.request, urllib.parse, urllib.error, hmac, hashlib, os, sys, uuid
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

API_KEY = (ENV.get("BINANCE_TESTNET_API_KEY") or os.getenv("BINANCE_TESTNET_API_KEY") or "").strip()
API_SEC = (ENV.get("BINANCE_TESTNET_SECRET") or os.getenv("BINANCE_TESTNET_SECRET") or "").strip()
if not API_KEY or not API_SEC or "buraya" in API_KEY.lower():
    print("KRITIK: BINANCE_TESTNET_API_KEY / BINANCE_TESTNET_SECRET eksik veya .env icinde hala placeholder halde.")
    print("Once https://testnet.binancefuture.com adresinden testnet API anahtari olustur, .env dosyasina yapistir.")
    sys.exit(1)

app = Flask(__name__)
PORT = int(ENV.get("TESTNET_PORT", "8081"))
BASE_URL = (ENV.get("BINANCE_TESTNET_URL") or "https://testnet.binancefuture.com").rstrip("/")

# Referans TL takibi (sadece log/goruntuleme -- islem mantigini etkilemez)
REF_CAPITAL_TL = float(ENV.get("TESTNET_REF_CAPITAL_TL", "1000"))
_tl_rate_raw = (ENV.get("TL_USD_RATE") or "").strip()
try:
    TL_USD_RATE = float(_tl_rate_raw)
except Exception:
    TL_USD_RATE = 0.0  # kur girilmemis -- TL donusumu loglarda gosterilmeyecek

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
FALLBACK = {"BTCUSDT": 64000.0, "ETHUSDT": 1870.0, "SOLUSDT": 76.0, "BNBUSDT": 600.0}
DEFAULT_FILTER = {"stepSize": 0.001, "minQty": 0.001, "minNotional": 5.0, "tickSize": 0.01}
SYMBOL_FILTERS = {}
last_px = dict(FALLBACK)

RISK = float(ENV.get("TESTNET_RISK", "0.20"))
LEV = float(ENV.get("TESTNET_LEVERAGE", "20"))
TP_M = float(ENV.get("TESTNET_TP_M", "10.0"))
FEE = float(ENV.get("FEE_RATE", "0.0004"))  # testnet de canliyla ayni ucret oranini kullanir -- gercekci kalsin
TP_P = TP_M / LEV
SL_P = float(ENV.get("TESTNET_SL_P", "0.90"))
HOLD_MAX = int(ENV.get("TESTNET_HOLD_MAX", "15"))
INTERVAL = int(ENV.get("TESTNET_INTERVAL", "6"))
COOLDOWN = int(ENV.get("TESTNET_COOLDOWN", "1"))
MAX_POS_USDT = float(ENV.get("TESTNET_MAX_POS_USDT", "200"))
MIN_MARGIN = 0.25
RECV_WINDOW = 5000
MAX_RETRIES = 4
CB_THRESHOLD = 3
CB_COOLDOWN = 15

balance = 0.0
peak = 0.0
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
    line = time.strftime("%H:%M:%S") + " [TESTNET] " + safe(msg)
    with lock:
        logs.insert(0, line)
        if len(logs) > 300:
            logs.pop()
    print(line, flush=True)

def tl_str(usdt_amount):
    """Sadece goruntuleme: USDT tutarini TL karsiligina cevirip okunur bir ek metin dondurur."""
    if TL_USD_RATE <= 0:
        return ""
    return " (~%.2f TL)" % (usdt_amount * TL_USD_RATE)

def sync_server_time():
    global time_offset
    try:
        start = int(time.time() * 1000)
        req = urllib.request.Request(BASE_URL + "/fapi/v1/time", headers={"User-Agent": "hc-testnet"})
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
    """
    Testnet icin GERCEK imzali istek katmani. engine_alpha.py (canli) ile
    birebir ayni mantik -- tek fark BASE_URL ve API_KEY/API_SEC testnet'e ait.
    HTTPError govdesi (code/msg) her zaman loglanir; 4xx hatalari retry
    edilmez (istemci hatasi tekrar denemeyle duzelmez); yazma islemlerinde
    (allow_retry=False) kor retry yapilmaz -- cift emir riskini onler.
    """
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
            "User-Agent": "hc-testnet"
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
    return "tn-%s-%d-%s" % (prefix, int(time.time() * 1000), uuid.uuid4().hex[:8])

def place_market(symbol, side, qty, position_side=None, reduce_only=False, client_id=None):
    params = {
        "symbol": symbol,
        "side": side,
        "type": "MARKET",
        "quantity": qty,
    }
    if position_side:
        params["positionSide"] = position_side
    if reduce_only and (not position_side or position_side == "BOTH"):
        params["reduceOnly"] = "true"
    if client_id:
        params["newClientOrderId"] = client_id
    return binance_request("POST", "/fapi/v1/order", params, allow_retry=False)

def fetch_px(symbol):
    """Testnet fiyat endpoint'i -- gercek testnet emir defteri fiyatidir, canli borsa fiyati DEGILDIR."""
    try:
        url = BASE_URL + "/fapi/v1/ticker/price?symbol=" + symbol
        req = urllib.request.Request(url, headers={"Connection": "close", "User-Agent": "hc-testnet"})
        with urllib.request.urlopen(req, timeout=3) as r:
            px = float(json.loads(r.read().decode("utf-8"))["price"])
            last_px[symbol] = px
            return px, "testnet-canli"
    except Exception:
        return last_px.get(symbol, FALLBACK[symbol]), "yedek"

def fetch_klines(symbol, limit=50):
    try:
        url = BASE_URL + "/fapi/v1/klines?symbol=%s&interval=1m&limit=%d" % (symbol, limit)
        req = urllib.request.Request(url, headers={"User-Agent": "hc-testnet"})
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

        real = get_balance_usdt()
        if real > 0:
            balance = real

        margin = balance * RISK
        if margin < MIN_MARGIN:
            global skip_log_counter
            skip_log_counter += 1
            if skip_log_counter % 8 == 1:
                log("Yetersiz margin (%.2f USDT%s), islem acilmadi" % (margin, tl_str(margin)))
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
            log("GERCEK TESTNET EMRI KABUL EDILDI | Emir No: %s | ClientID: %s | Fiyat: %.4f | Miktar: %s | Yon: %s" % (
                oid, cid, exec_px, qty, side))
        except Exception as e:
            cb_hit()
            log("Acilis basarisiz (testnet borsasi reddetti): %s" % e)
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
            "POZISYON ACILDI (GERCEK TESTNET) | %s %s | Giris: %.4f | Margin: %.2f USDT%s | "
            "Notional: %.2f USDT%s | Kaldirac: %.0fx | TP: %.4f (+%.2f%%) | SL: %.4f | "
            "Acilis ucreti: %.4f USDT%s | Sinyal: %s | Kalan bakiye: %.2f USDT%s" % (
                side, symbol, px, margin, tl_str(margin), notional, tl_str(notional),
                LEV, tp, TP_P, sl, open_fee, tl_str(open_fee), reason, balance, tl_str(balance))
        )

def close_pos(pos, px, reason, src):
    """
    Birincil kapatma yolu: borsadan okunan GERCEK pozisyon miktariyla
    reduceOnly=true MARKET emri. (closePosition=true testnet'te de
    canli motordaki gibi -4136 hatasi verebilir -- bu yuzden kullanilmiyor.)
    """
    global balance, peak
    pos_side = pos.get("pos_side")
    real_qty = get_position_amt(pos["symbol"], pos["side"])
    if real_qty <= 0:
        log("Kapatma iptal: Testnet borsasinda acik pozisyon yok")
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
        log("KAPATMA EMRI KABUL EDILDI (GERCEK TESTNET) | Emir No: %s | Cikis: %.4f" % (res.get("orderId"), px))
    except Exception as e:
        cb_hit()
        log("Kapatma basarisiz — pozisyon testnet'te HALA ACIK OLABILIR, kontrol et: %s" % e)
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
    # Aciklamali, tek satirda okunabilir kar/zarar/ucret dokumu
    log(
        "POZISYON KAPANDI | %s %s | Kapanma sebebi: %s | Giris: %.4f -> Cikis: %.4f (fiyat hareketi %.3f%%) | "
        "ISLEM UCRETLERI toplam: %.4f USDT%s (acilis %.4f + kapanis %.4f) | "
        "NET SONUC: %.4f USDT%s (%s, marjin uzerinden %.1f%%) | "
        "Yeni bakiye: %.2f USDT%s | Zirveden dususs (drawdown): %.1f%%" % (
            pos["side"], pos["symbol"], reason, pos["entry"], px, move,
            fees, tl_str(fees), pos["open_fee"], close_fee,
            net, tl_str(net), sonuc, m_pct,
            bal, tl_str(bal), dd)
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

def reconcile_on_start():
    try:
        for sym in SYMBOLS:
            for side in ("LONG", "SHORT"):
                amt = get_position_amt(sym, side)
                if amt > 0:
                    log("UYARI: Baslangicta testnet'te takip edilmeyen ACIK pozisyon bulundu: %s %s miktar=%.6f" % (sym, side, amt))
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
    else:
        log("UYARI: Testnet bakiyesi 0 gorunuyor. Binance testnet hesabinda faucet'ten sahte USDT talep et.")

    tl_line = ""
    if TL_USD_RATE > 0:
        tl_line = " | Referans sermaye: %.0f TL (kur: %.2f)" % (REF_CAPITAL_TL, TL_USD_RATE)

    log(
        "GERCEK TESTNET MOTORU BASLADI | Testnet bakiyesi: %.2f USDT%s | Risk: %.0f%% | Kaldirac: %.0fx | "
        "TP: %.2f%% | SL: %.2f%% | Hold: %d tick | Filtre: EMA9/21 + RSI%s" % (
            balance, tl_str(balance), RISK * 100, LEV, TP_P, SL_P, HOLD_MAX, tl_line)
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
                        "Anlik PnL: %.4f USDT%s (%.1f%%) %s | TP uzak: %.3f%% | SL uzak: %.3f%%" % (
                            pos["side"], pos["symbol"], pos["ticks"], HOLD_MAX, px,
                            unreal, tl_str(unreal), unreal_pct, durum, dtp, dsl)
                    )
            else:
                if idle > 0:
                    idle -= 1
                else:
                    sym = SYMBOLS[i % len(SYMBOLS)]
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
    return jsonify({"ok": 1, "i": state["i"], "age": round(time.time() - state["last"], 1), "engine": "testnet-gercek"})

@app.route("/status")
def status():
    with lock:
        n = sum(1 for p in positions.values() if p.get("status") == "OPEN")
        return jsonify({
            "balance_usdt": round(balance, 2),
            "balance_tl_approx": round(balance * TL_USD_RATE, 2) if TL_USD_RATE > 0 else None,
            "open": n, "lev": LEV, "trades": len(journal), "mode": "TESTNET-GERCEK"
        })

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
        "balance_usdt": round(balance, 2),
        "balance_tl_approx": round(balance * TL_USD_RATE, 2) if TL_USD_RATE > 0 else None,
        "net_pnl_total_usdt": round(net, 4),
        "total_fees_paid_usdt": round(fees, 4),
        "trades": len(jn),
        "wins": len(wins),
        "losses": len(jn) - len(wins),
        "win_rate": round(100.0 * len(wins) / len(jn), 1) if jn else 0,
        "leverage": LEV,
        "mode": "TESTNET-GERCEK"
    })

if __name__ == "__main__":
    threading.Thread(target=loop, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True, use_reloader=False)
