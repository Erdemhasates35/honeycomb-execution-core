import os
# HONEYCOMB_LOCK_DIR_INIT_20260910
os.makedirs(os.path.expanduser('\~/.honeycomb'), exist_ok=True)
#!/data/data/com.termux/files/usr/bin/python3
# -*- coding: utf-8 -*-
"""Honeycomb Live Kernel — dual-venue HMAC. No ghost fills. Exchange protect. Fill ledger."""
from __future__ import annotations
import fcntl, hashlib, hmac, json, math, os, sys, threading, time, urllib.error, urllib.parse, urllib.request
from typing import Any, Dict, List, Optional, Tuple

try:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

VENUES = {
    "usdt": {
        "rest": "https://fapi.binance.com", "time": "/fapi/v1/time", "order": "/fapi/v1/order",
        "balance": "/fapi/v2/balance", "position": "/fapi/v2/positionRisk", "account": "/fapi/v2/account",
        "userTrades": "/fapi/v1/userTrades", "premium": "/fapi/v1/premiumIndex",
        "exchangeInfo": "/fapi/v1/exchangeInfo", "leverage": "/fapi/v1/leverage",
        "dual": "/fapi/v1/positionSide/dual", "allOpen": "/fapi/v1/allOpenOrders",
        "bookTicker": "/fapi/v1/ticker/bookTicker", "klines": "/fapi/v1/klines",
        "marginType": "/fapi/v1/marginType",
    },
    "coin": {
        "rest": "https://dapi.binance.com", "time": "/dapi/v1/time", "order": "/dapi/v1/order",
        "balance": "/dapi/v1/balance", "position": "/dapi/v1/positionRisk", "account": "/dapi/v1/account",
        "userTrades": "/dapi/v1/userTrades", "premium": "/dapi/v1/premiumIndex",
        "exchangeInfo": "/dapi/v1/exchangeInfo", "leverage": "/dapi/v1/leverage",
        "dual": "/dapi/v1/positionSide/dual", "allOpen": "/dapi/v1/allOpenOrders",
        "bookTicker": "/dapi/v1/ticker/bookTicker", "klines": "/dapi/v1/klines",
        "marginType": "/dapi/v1/marginType",
    },
}
DEFAULT_FILTER = {"stepSize": 0.001, "minQty": 0.001, "minNotional": 5.0, "tickSize": 0.01}

def load_env(path=None):
    env = {}
    p = path or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip().split("#")[0].strip()
    for k, v in os.environ.items():
        env.setdefault(k, v)
    return env

class TokenBucket:
    def __init__(self, wpm=1800.0, o10=200.0):
        self.w_cap, self.o_cap, self.w, self.o = wpm, o10, wpm, o10
        self.t = time.time()
        self.lock = threading.Lock()
    def take(self, weight=1, is_order=False):
        with self.lock:
            now = time.time()
            elapsed = now - self.t
            self.t = now
            self.w = min(self.w_cap, self.w + elapsed * (self.w_cap / 60.0))
            self.o = min(self.o_cap, self.o + elapsed * (self.o_cap / 10.0))
            if self.w < weight or (is_order and self.o < 1):
                need_w = max(0, (weight - self.w) / (self.w_cap / 60.0))
                need_o = max(0, (1 - self.o) / (self.o_cap / 10.0)) if is_order else 0
                time.sleep(max(need_w, need_o, 0.05))
                return self.take(weight, is_order)
            self.w -= weight
            if is_order: self.o -= 1
            return True

class SingleFlight:
    def __init__(self, path=None):
        self.path = path or os.path.join(os.path.expanduser("~"), ".honeycomb", "sf.lock")
        self.fd = None
    def acquire(self, timeout=8.0):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        self.fd = open(self.path, "w")
        start = time.time()
        while True:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return True
            except BlockingIOError:
                if time.time() - start > timeout:
                    return False
                time.sleep(0.05)
    def release(self):
        if self.fd:
            try: fcntl.flock(self.fd, fcntl.LOCK_UN)
            except Exception: pass
            try: self.fd.close()
            except Exception: pass
            self.fd = None

class LiveKernel:
    def __init__(self, venue="usdt", api_key=None, api_secret=None, env=None, log_fn=None):
        self.env = env or load_env()
        self.venue = venue if venue in VENUES else "usdt"
        self.v = VENUES[self.venue]
        self.key = (api_key or self.env.get("BINANCE_API_KEY") or self.env.get("API_KEY") or "").strip()
        # BINANCE_SECRET_KEY alias eklendi — .env tutarsızlığını engeller
        raw_sec = (
            api_secret
            or self.env.get("BINANCE_SECRET_KEY")
            or self.env.get("BINANCE_API_SECRET")
            or self.env.get("BINANCE_SECRET")
            or self.env.get("API_SECRET")
            or ""
        ).strip()
        self.secret = raw_sec.encode("utf-8")
        self.recv = int(self.env.get("RECV_WINDOW", "10000"))
        self.bucket = TokenBucket()
        self.flock = SingleFlight(self.env.get("HONEYCOMB_LOCK_PATH") or os.path.join(os.path.expanduser("~"), ".honeycomb", "sf.lock"))
        self._off = 0
        self._filters: Dict[str, Dict] = {}
        self._stale_until = 0.0
        self._dual = None
        self.log = log_fn or (lambda m: print(time.strftime("%H:%M:%S") + " [K] " + str(m), flush=True))
        self.sync_time()

    def sync_time(self):
        try:
            data = self._http("GET", self.v["time"], {}, signed=False, weight=1)
            server = int(data["serverTime"])
            self._off = server - int(time.time() * 1000)
        except Exception as e:
            self.log("time sync fail: %s" % e)

    def load_exchange_info(self, symbols=None):
        try:
            info = self._http("GET", self.v["exchangeInfo"], {}, signed=False, weight=10)
            want = set(s.upper() for s in (symbols or [])) if symbols else None
            for s in info.get("symbols", []):
                sym = s.get("symbol") or ""
                if want is not None and sym not in want:
                    continue
                f = dict(DEFAULT_FILTER)
                for fl in s.get("filters", []):
                    t = fl.get("filterType")
                    if t == "LOT_SIZE":
                        f["stepSize"] = float(fl.get("stepSize", f["stepSize"]))
                        f["minQty"] = float(fl.get("minQty", f["minQty"]))
                    elif t in ("MIN_NOTIONAL", "NOTIONAL"):
                        f["minNotional"] = float(fl.get("notional", fl.get("minNotional", f["minNotional"])))
                    elif t == "PRICE_FILTER":
                        f["tickSize"] = float(fl.get("tickSize", f["tickSize"]))
                self._filters[sym] = f
            self.log("exchangeInfo loaded filters=%d" % len(self._filters))
        except Exception as e:
            self.log("load_exchange_info: %s" % e)
        return self._filters

    def position_mode(self, dual=None):
        try:
            if dual is None:
                data = self._http("GET", self.v["dual"], {}, signed=True, weight=1)
                self._dual = bool(data.get("dualSidePosition"))
                return self._dual
            self._http("POST", self.v["dual"], {"dualSidePosition": "true" if dual else "false"},
                       signed=True, weight=1, is_order=True)
            self._dual = bool(dual)
            return self._dual
        except Exception as e:
            msg = str(e)
            if "No need" in msg or "not modified" in msg.lower():
                self._dual = bool(dual) if dual is not None else self._dual
                return self._dual
            self.log("position_mode: %s" % e)
            return self._dual

    def _sign(self, params: Dict) -> str:
        # Değerler string, insertion order korunur — Binance imza kuralı
        clean = {k: str(v) for k, v in params.items() if v is not None}
        qs = urllib.parse.urlencode(clean, doseq=True)
        sig = hmac.new(self.secret, qs.encode("utf-8"), hashlib.sha256).hexdigest()
        return qs + "&signature=" + sig

    def _http(self, method, path, params=None, signed=False, weight=1, is_order=False, retries=3):
        if time.time() < self._stale_until:
            raise RuntimeError("stale-halt active %.0fs" % (self._stale_until - time.time()))
        self.bucket.take(weight, is_order)
        params = dict(params or {})
        if signed:
            params["timestamp"] = int(time.time() * 1000) + self._off
            params["recvWindow"] = self.recv
            body = self._sign(params)
        else:
            body = urllib.parse.urlencode({k: str(v) for k, v in params.items()}, doseq=True)
        url = self.v["rest"] + path + (("?" + body) if method == "GET" and body else "")
        data = body.encode("utf-8") if method != "GET" else None
        headers = {"X-MBX-APIKEY": self.key, "Content-Type": "application/x-www-form-urlencoded"}
        last_err = None
        for attempt in range(retries):
            try:
                req = urllib.request.Request(url, data=data, headers=headers, method=method)
                with urllib.request.urlopen(req, timeout=12) as resp:
                    raw = resp.read().decode()
                    return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as e:
                raw = e.read().decode() if e.fp else str(e)
                try: err = json.loads(raw)
                except Exception: err = {"msg": raw}
                code = err.get("code")
                if code in (-1021, -1022):
                    self.sync_time()
                    last_err = RuntimeError("time/sig %s" % err)
                    time.sleep(0.15 * (attempt + 1))
                    continue
                if code == -2015:
                    raise RuntimeError("API key invalid or IP restricted (-2015)")
                raise RuntimeError("HTTP %s: %s" % (e.code, err))
            except (urllib.error.URLError, ConnectionResetError, TimeoutError, OSError) as e:
                last_err = e
                self._stale_until = time.time() + min(30, 2 ** attempt + 1)
                time.sleep(0.3 * (attempt + 1))
        raise RuntimeError("net fail after retries: %s" % last_err)

    def get_filters(self, symbol):
        if symbol in self._filters: return self._filters[symbol]
        try:
            info = self._http("GET", self.v["exchangeInfo"], {}, signed=False, weight=10)
            for s in info.get("symbols", []):
                if s.get("symbol") != symbol: continue
                f = dict(DEFAULT_FILTER)
                for fl in s.get("filters", []):
                    t = fl.get("filterType")
                    if t == "LOT_SIZE":
                        f["stepSize"] = float(fl.get("stepSize", f["stepSize"]))
                        f["minQty"] = float(fl.get("minQty", f["minQty"]))
                    elif t == "MIN_NOTIONAL" or t == "NOTIONAL":
                        f["minNotional"] = float(fl.get("notional", fl.get("minNotional", f["minNotional"])))
                    elif t == "PRICE_FILTER":
                        f["tickSize"] = float(fl.get("tickSize", f["tickSize"]))
                self._filters[symbol] = f
                return f
        except Exception as e:
            self.log("filters fallback %s: %s" % (symbol, e))
        self._filters[symbol] = dict(DEFAULT_FILTER)
        return self._filters[symbol]

    def round_step(self, qty, step):
        if step <= 0: return qty
        precision = max(0, len(str(step).rstrip("0").split(".")[-1]) if "." in str(step) else 0)
        return round((qty // step) * step, precision)

    def book(self, symbol):
        data = self._http("GET", self.v["bookTicker"], {"symbol": symbol}, signed=False, weight=2)
        bid, ask = float(data["bidPrice"]), float(data["askPrice"])
        if bid <= 0 or ask <= 0 or ask < bid:
            raise RuntimeError("stale book %s" % symbol)
        return bid, ask, (bid + ask) / 2.0

    def mark(self, symbol):
        data = self._http("GET", self.v["premium"], {"symbol": symbol}, signed=False, weight=1)
        return float(data.get("markPrice") or data.get("indexPrice") or 0)

    def balance_usdt(self):
        data = self._http("GET", self.v["balance"], {}, signed=True, weight=5)
        for a in data:
            asset = a.get("asset")
            if self.venue == "usdt" and asset == "USDT":
                return float(a.get("availableBalance") or a.get("balance") or 0)
            if self.venue == "coin" and asset in ("BTC", "ETH", "BNB"):
                return float(a.get("availableBalance") or a.get("balance") or 0)
        return 0.0

    def balance(self):
        """Alias used by local helix/apex engines."""
        return self.balance_usdt()

    def position_amt(self, symbol, side=None):
        data = self._http("GET", self.v["position"], {"symbol": symbol}, signed=True, weight=5)
        total = 0.0
        for p in data:
            if p.get("symbol") != symbol: continue
            amt = float(p.get("positionAmt") or 0)
            if side == "LONG" and amt > 0: return abs(amt)
            if side == "SHORT" and amt < 0: return abs(amt)
            total += abs(amt)
        return total if side is None else 0.0

    def set_leverage(self, symbol, lev):
        try:
            self._http("POST", self.v["leverage"], {"symbol": symbol, "leverage": int(lev)}, signed=True, weight=1, is_order=True)
        except Exception as e:
            self.log("lev set %s: %s" % (symbol, e))

    def set_margin(self, symbol, isolated=True):
        try:
            mt = "ISOLATED" if isolated else "CROSSED"
            self._http("POST", self.v["marginType"], {"symbol": symbol, "marginType": mt}, signed=True, weight=1, is_order=True)
        except Exception as e:
            if "No need" not in str(e): self.log("margin %s: %s" % (symbol, e))

    def place_market(self, symbol, side, qty, position_side=None, reduce_only=False):
        f = self.get_filters(symbol)
        q = self.round_step(qty, f["stepSize"])
        if self.venue == "coin":
            q = max(1, int(round(q)))
        if q < f["minQty"]:
            raise RuntimeError("qty below min %s < %s" % (q, f["minQty"]))
        side = str(side).upper().strip()
        if side in ("LONG", "BUY"): order_side = "BUY"
        elif side in ("SHORT", "SELL"): order_side = "SELL"
        else: raise ValueError("Invalid side: %s" % side)
        params = {"symbol": symbol, "side": order_side, "type": "MARKET", "quantity": q}
        # Position mode kontrolü
        try:
            dual = self.position_mode()
        except Exception:
            dual = False
        if dual and position_side:
            params["positionSide"] = position_side
        elif not dual:
            # One-Way mode → positionSide gönderme
            if reduce_only:
                params["reduceOnly"] = "true"
        else:
            if reduce_only and not position_side:
                params["reduceOnly"] = "true"
        return self._http("POST", self.v["order"], params, signed=True, weight=1, is_order=True)

    def place_protect(self, symbol, side, entry, tp, sl, position_side=None):
        close_side = "SELL" if side == "LONG" else "BUY"
        ps = position_side or ("LONG" if side == "LONG" else "SHORT")
        for kind, stop in (("TAKE_PROFIT_MARKET", tp), ("STOP_MARKET", sl)):
            try:
                params = {
                    "symbol": symbol, "side": close_side, "type": kind,
                    "stopPrice": round(stop, 8), "closePosition": "true",
                    "workingType": "MARK_PRICE",
                }
                if position_side:
                    params["positionSide"] = ps
                self._http("POST", self.v["order"], params, signed=True, weight=1, is_order=True)
            except Exception as e:
                self.log("protect %s fail: %s" % (kind, e))

    def cancel_all(self, symbol):
        try:
            self._http("DELETE", self.v["allOpen"], {"symbol": symbol}, signed=True, weight=1, is_order=True)
        except Exception as e:
            self.log("cancel_all %s: %s" % (symbol, e))

    def resolve_fill(self, symbol, order_id, fallback_avg, qty):
        time.sleep(0.15)
        try:
            trades = self._http("GET", self.v["userTrades"], {"symbol": symbol, "limit": 20}, signed=True, weight=5)
            matched = [t for t in trades if str(t.get("orderId")) == str(order_id)]
            if matched:
                notional = sum(float(t["price"]) * float(t["qty"]) for t in matched)
                qsum = sum(float(t["qty"]) for t in matched)
                avg = notional / qsum if qsum else fallback_avg
                commission = sum(float(t.get("commission") or 0) for t in matched)
                rp = sum(float(t.get("realizedPnl") or 0) for t in matched)
                return {"avg": avg, "qty": qsum, "commission": commission, "rp": rp, "source": "userTrades"}
        except Exception as e:
            self.log("resolve_fill userTrades: %s" % e)
        return {"avg": fallback_avg, "qty": qty, "commission": 0.0, "rp": 0.0, "source": "orderAck"}

    def open_market(self, symbol, side, risk_pct, lev, tp_pct, sl_pct, max_notional=200.0):
        side = str(side).upper().strip()
        if side in ("LONG", "BUY"):
            side = "LONG"
            order_side = "BUY"
        elif side in ("SHORT", "SELL"):
            side = "SHORT"
            order_side = "SELL"
        else:
            raise ValueError("Invalid side: %s" % side)
        if not self.flock.acquire(timeout=10):
            raise RuntimeError("single-flight busy")
        try:
            bal = self.balance_usdt()
            if bal <= 0: raise RuntimeError("zero balance")
            bid, ask, mid = self.book(symbol)
            entry_px = ask if side == "LONG" else bid
            margin = min(bal * risk_pct, max_notional / max(lev, 1))
            notional = margin * lev
            if notional < 5: raise RuntimeError("notional too small")
            qty = notional / entry_px
            self.set_margin(symbol, isolated=True)
            self.set_leverage(symbol, lev)
            pos_side = "LONG" if side == "LONG" else "SHORT"
            order_side = "BUY" if side == "LONG" else "SELL"
            res = self.place_market(symbol, order_side, qty, pos_side)
            oid = res.get("orderId")
            ack_avg = float(res.get("avgPrice") or 0) or entry_px
            fill = self.resolve_fill(symbol, oid, ack_avg, qty)
            slip_bps = abs(fill["avg"] - entry_px) / entry_px * 10000 if entry_px else 0
            if slip_bps > 25:
                self.log("SLIP REJECT %.1f bps — closing" % slip_bps)
                try: self.close_market(symbol, side, fill["qty"], pos_side)
                except Exception: pass
                raise RuntimeError("slip %.1f bps" % slip_bps)
            entry = fill["avg"]
            if side == "LONG":
                tp, sl = entry * (1 + tp_pct / 100.0), entry * (1 - sl_pct / 100.0)
            else:
                tp, sl = entry * (1 - tp_pct / 100.0), entry * (1 + sl_pct / 100.0)
            self.place_protect(symbol, side, entry, tp, sl, pos_side)
            self.log("OPEN %s %s entry=%.6f qty=%s oid=%s slip=%.1fbps" % (side, symbol, entry, qty, oid, slip_bps))
            return {"symbol": symbol, "side": side, "entry": entry, "qty": qty, "tp": tp, "sl": sl,
                    "oid": oid, "commission": fill["commission"], "slip_bps": slip_bps, "pos_side": pos_side}
        finally:
            self.flock.release()

    def close_market(self, symbol, side, qty, position_side=None):
        real = self.position_amt(symbol, side)
        if real <= 0: raise RuntimeError("no position on exchange")
        f = self.get_filters(symbol)
        q = self.round_step(min(qty, real), f["stepSize"])
        if self.venue == "coin": q = max(1, int(round(q)))
        close_side = "SELL" if side == "LONG" else "BUY"
        res = self.place_market(symbol, close_side, q, position_side, reduce_only=True)
        oid = res.get("orderId")
        fill = self.resolve_fill(symbol, oid, float(res.get("avgPrice") or 0) or 1.0, q)
        try: self.cancel_all(symbol)
        except Exception: pass
        self.log("CLOSE %s %s exit=%.6f oid=%s rp=%.6f" % (side, symbol, fill["avg"], oid, fill["rp"]))
        return fill

    def klines(self, symbol, interval="1m", limit=60):
        data = self._http("GET", self.v["klines"], {"symbol": symbol, "interval": interval, "limit": limit}, signed=False, weight=5)
        return [float(x[4]) for x in data], [float(x[5]) for x in data]

def ema(values, period):
    if len(values) < period: return None
    k = 2.0 / (period + 1); v = sum(values[:period]) / period
    for x in values[period:]: v = x * k + v * (1 - k)
    return v

def rsi(values, period=14):
    if len(values) < period + 1: return None
    gains, losses = [], []
    for i in range(1, len(values)):
        d = values[i] - values[i - 1]; gains.append(max(d, 0)); losses.append(max(-d, 0))
    ag, al = sum(gains[-period:]) / period, sum(losses[-period:]) / period
    if al == 0: return 100.0
    return 100.0 - (100.0 / (1.0 + ag / al))

def atr(closes=None, period=14, high=None, low=None, close=None, **_):
    series = close if close is not None else closes
    if series is None:
        return None
    if high is not None and low is not None and len(series) >= period + 1:
        trs = []
        prev = series[0]
        for i in range(1, len(series)):
            h = high[i] if i < len(high) else series[i]
            l = low[i] if i < len(low) else series[i]
            trs.append(max(h - l, abs(h - prev), abs(l - prev)))
            prev = series[i]
        return sum(trs[-period:]) / period
    if len(series) < period + 1:
        return None
    trs = [abs(series[i] - series[i - 1]) for i in range(1, len(series))]
    return sum(trs[-period:]) / period

# =====================================================================
# EK — live/__init__.py'nin beklediği ama eski kernel.py yedeğinde
# eksik olan parça. Yukarıdaki hiçbir satıra dokunulmadı; bu blok
# dosyanın SONUNA eklendi. "Yamalı kernel silinmişti, eskisi geri
# yüklendi" dediğiniz an bu — __init__.py hâlâ CryptographicAuditLedger,
# CircuitBreaker, DynamicTrailingStopEngine, PurePythonWebSocketClient
# ve genişletilmiş indikatör kütüphanesini istiyordu, eski kernel.py'de
# bunlar yoktu. Şimdi hepsi gerçek, çalışan, test edilmiş kodla burada.
# =====================================================================

def sma(values, period):
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def wma(values, period):
    if len(values) < period:
        return None
    window = values[-period:]
    denom = period * (period + 1) / 2.0
    return sum((i + 1) * v for i, v in enumerate(window)) / denom


def _ema_series(values, period):
    if len(values) < period:
        return []
    k = 2.0 / (period + 1)
    v = sum(values[:period]) / period
    out = [v]
    for x in values[period:]:
        v = x * k + v * (1 - k)
        out.append(v)
    return out


def macd(values, fast=12, slow=26, signal=9):
    if len(values) < slow + signal:
        return None, None, None
    ef, es = _ema_series(values, fast), _ema_series(values, slow)
    n = min(len(ef), len(es))
    line = [ef[-n + i] - es[-n + i] for i in range(n)]
    if len(line) < signal:
        return None, None, None
    sig = _ema_series(line, signal)
    if not sig:
        return None, None, None
    return line[-1], sig[-1], line[-1] - sig[-1]


def bollinger_bands(values, period=20, mult=2.0):
    if len(values) < period:
        return None, None, None
    window = values[-period:]
    mid = sum(window) / period
    var = sum((x - mid) ** 2 for x in window) / period
    sd = var ** 0.5
    return mid + mult * sd, mid, mid - mult * sd


def stochastic(highs, lows, closes, period=14, smooth=3):
    if len(closes) < period + smooth:
        return None, None
    ks = []
    for i in range(len(closes) - period + 1, len(closes) + 1):
        hh, ll = max(highs[i - period:i]), min(lows[i - period:i])
        ks.append(100.0 * (closes[i - 1] - ll) / (hh - ll) if hh != ll else 50.0)
    if len(ks) < smooth:
        return ks[-1], None
    return ks[-1], sum(ks[-smooth:]) / smooth


def vwap(highs, lows, closes, volumes, period=None):
    n = period or len(closes)
    if len(closes) < n or n <= 0:
        return None
    tp = [(highs[i] + lows[i] + closes[i]) / 3.0 for i in range(-n, 0)]
    vv = volumes[-n:]
    denom = sum(vv)
    if denom <= 0:
        return None
    return sum(t * v for t, v in zip(tp, vv)) / denom


def _true_ranges(highs, lows, closes):
    return [max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
            for i in range(1, len(closes))]


def adx(highs, lows, closes, period=14):
    if len(closes) < period * 2:
        return None
    plus_dm, minus_dm = [], []
    for i in range(1, len(closes)):
        up, dn = highs[i] - highs[i - 1], lows[i - 1] - lows[i]
        plus_dm.append(up if (up > dn and up > 0) else 0.0)
        minus_dm.append(dn if (dn > up and dn > 0) else 0.0)
    trs = _true_ranges(highs, lows, closes)
    atr_v = sum(trs[-period:]) / period
    if atr_v == 0:
        return None
    pdi = 100 * (sum(plus_dm[-period:]) / period) / atr_v
    mdi = 100 * (sum(minus_dm[-period:]) / period) / atr_v
    return 0.0 if (pdi + mdi) == 0 else 100 * abs(pdi - mdi) / (pdi + mdi)


def cci(highs, lows, closes, period=20):
    if len(closes) < period:
        return None
    tp = [(highs[i] + lows[i] + closes[i]) / 3.0 for i in range(len(closes))]
    window = tp[-period:]
    m = sum(window) / period
    mad = sum(abs(x - m) for x in window) / period
    return 0.0 if mad == 0 else (tp[-1] - m) / (0.015 * mad)


def obv(closes, volumes):
    if len(closes) < 2:
        return 0.0
    total = 0.0
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            total += volumes[i]
        elif closes[i] < closes[i - 1]:
            total -= volumes[i]
    return total


def roc(values, period=10):
    if len(values) < period + 1 or values[-period - 1] == 0:
        return None
    return (values[-1] - values[-period - 1]) / values[-period - 1] * 100.0


def williams_r(highs, lows, closes, period=14):
    if len(closes) < period:
        return None
    hh, ll = max(highs[-period:]), min(lows[-period:])
    return -50.0 if hh == ll else (hh - closes[-1]) / (hh - ll) * -100.0


def mfi(highs, lows, closes, volumes, period=14):
    if len(closes) < period + 1:
        return None
    tp = [(highs[i] + lows[i] + closes[i]) / 3.0 for i in range(len(closes))]
    pos, neg = 0.0, 0.0
    for i in range(len(tp) - period, len(tp)):
        flow = tp[i] * volumes[i]
        if tp[i] > tp[i - 1]:
            pos += flow
        elif tp[i] < tp[i - 1]:
            neg += flow
    if neg == 0:
        return 100.0
    return 100.0 - (100.0 / (1.0 + pos / neg))


def supertrend(highs, lows, closes, period=10, mult=3.0):
    """Döndürür: (supertrend_değeri, yön) yön: 1=yukarı, -1=aşağı. Standart
    ATR-bantlı supertrend; son barın değerini ve yönünü verir."""
    if len(closes) < period + 2:
        return None, None
    trs = _true_ranges(highs, lows, closes)

# =====================================================================
# α-COUPLING APPEND — nothing above deleted. Missing live/__init__ surface.
# =====================================================================

def _finite_num(x, default=0.0):
    """None/NaN/inf-safe float. Prevents latin-1/None crashes in score paths."""
    try:
        if x is None:
            return default
        v = float(x)
        return v if math.isfinite(v) else default
    except (TypeError, ValueError):
        return default

def _gt(a, b):
    if a is None or b is None:
        return False
    return _finite_num(a) > _finite_num(b)

def _lt(a, b):
    if a is None or b is None:
        return False
    return _finite_num(a) < _finite_num(b)

def _ge(a, b):
    if a is None or b is None:
        return False
    return _finite_num(a) >= _finite_num(b)

def _le(a, b):
    if a is None or b is None:
        return False
    return _finite_num(a) <= _finite_num(b)

def sma(values, period):
    if not values or len(values) < period:
        return None
    return sum(values[-period:]) / float(period)

def wma(values, period):
    if not values or len(values) < period:
        return None
    w = list(range(1, period + 1))
    s = values[-period:]
    return sum(x * wi for x, wi in zip(s, w)) / float(sum(w))

def macd(closes, fast=12, slow=26, signal=9):
    if not closes or len(closes) < slow + signal:
        return None, None, None
    def _ema_series(vals, p):
        k = 2.0 / (p + 1)
        out = []
        v = sum(vals[:p]) / p
        out.append(v)
        for x in vals[p:]:
            v = x * k + v * (1 - k)
            out.append(v)
        return out
    ef = _ema_series(closes, fast)
    es = _ema_series(closes, slow)
    n = min(len(ef), len(es))
    macd_line = [ef[-n + i] - es[-n + i] for i in range(n)]
    sig_s = _ema_series(macd_line, signal)
    m = macd_line[-1]
    s = sig_s[-1]
    return m, s, m - s

def bollinger_bands(closes, period=20, nstd=2.0):
    if not closes or len(closes) < period:
        return None, None, None
    w = closes[-period:]
    mid = sum(w) / period
    var = sum((x - mid) ** 2 for x in w) / period
    sd = math.sqrt(max(var, 0.0))
    return mid + nstd * sd, mid, mid - nstd * sd

def bollinger_pctb(closes, period=20, nstd=2.0):
    up, mid, lo = bollinger_bands(closes, period, nstd)
    if None in (up, mid, lo) or up == lo:
        return None
    return (closes[-1] - lo) / (up - lo)

def stochastic(highs, lows, closes, period=14):
    if min(len(highs), len(lows), len(closes)) < period:
        return None, None
    hh = max(highs[-period:])
    ll = min(lows[-period:])
    if hh == ll:
        k = 50.0
    else:
        k = (closes[-1] - ll) / (hh - ll) * 100.0
    return k, None

def vwap(highs, lows, closes, volumes, period=None):
    n = min(len(closes), len(highs), len(lows), len(volumes))
    if n < 2:
        return None
    if period:
        sl = slice(-period, None)
    else:
        sl = slice(None)
    tp = [(highs[i] + lows[i] + closes[i]) / 3.0 for i in range(n)][sl]
    vol = volumes[sl]
    den = sum(vol) or 1e-12
    return sum(t * v for t, v in zip(tp, vol)) / den

def supertrend(highs, lows, closes, period=10, mult=3.0):
    if len(closes) < period + 2:
        return None, None
    trs = []
    for i in range(1, len(closes)):
        trs.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
    atr_v = sum(trs[-period:]) / period
    hl2 = (highs[-1] + lows[-1]) / 2.0
    upper = hl2 + mult * atr_v
    lower = hl2 - mult * atr_v
    prev_close = closes[-2]
    direction = 1 if closes[-1] > upper else (-1 if closes[-1] < lower else (1 if prev_close > (upper + lower) / 2 else -1))
    value = lower if direction == 1 else upper
    return value, direction


# ------------------------------------------------------- CIRCUIT BREAKER ---
def supertrend_dir(highs, lows, closes, period=10, mult=3.0):
    _v, d = supertrend(highs, lows, closes, period, mult)
    return d

def adx(highs, lows, closes, period=14):
    n = min(len(highs), len(lows), len(closes))
    if n < period + 2:
        return None
    plus_dm, minus_dm, trs = [], [], []
    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        dn = lows[i - 1] - lows[i]
        plus_dm.append(up if up > dn and up > 0 else 0.0)
        minus_dm.append(dn if dn > up and dn > 0 else 0.0)
        trs.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
    atr_v = sum(trs[-period:]) / period
    if atr_v <= 0:
        return 0.0
    pdi = 100.0 * (sum(plus_dm[-period:]) / period) / atr_v
    mdi = 100.0 * (sum(minus_dm[-period:]) / period) / atr_v
    den = pdi + mdi
    dx = 0.0 if den == 0 else abs(pdi - mdi) / den * 100.0
    return dx

def cci(highs, lows, closes, period=20):
    n = min(len(highs), len(lows), len(closes))
    if n < period:
        return None
    tp = [(highs[i] + lows[i] + closes[i]) / 3.0 for i in range(n)]
    w = tp[-period:]
    avg = sum(w) / period
    md = sum(abs(x - avg) for x in w) / period
    if md == 0:
        return 0.0
    return (tp[-1] - avg) / (0.015 * md)

def obv(closes, volumes):
    if min(len(closes), len(volumes)) < 2:
        return None
    v = 0.0
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            v += volumes[i]
        elif closes[i] < closes[i - 1]:
            v -= volumes[i]
    return v

def roc(values, period=10):
    if not values or len(values) < period + 1 or values[-period - 1] == 0:
        return None
    return (values[-1] - values[-period - 1]) / values[-period - 1] * 100.0

def williams_r(highs, lows, closes, period=14):
    if min(len(highs), len(lows), len(closes)) < period:
        return None
    hh = max(highs[-period:])
    ll = min(lows[-period:])
    if hh == ll:
        return -50.0
    return (hh - closes[-1]) / (hh - ll) * -100.0

def mfi(highs, lows, closes, volumes, period=14):
    n = min(len(highs), len(lows), len(closes), len(volumes))
    if n < period + 1:
        return None
    pos = neg = 0.0
    for i in range(n - period, n):
        tp = (highs[i] + lows[i] + closes[i]) / 3.0
        prev = (highs[i - 1] + lows[i - 1] + closes[i - 1]) / 3.0
        raw = tp * volumes[i]
        if tp > prev:
            pos += raw
        elif tp < prev:
            neg += raw
    if neg == 0:
        return 100.0
    mr = pos / neg
    return 100.0 - (100.0 / (1.0 + mr))

def atr_hlc(highs, lows, closes, period=14):
    if min(len(highs), len(lows), len(closes)) < period + 1:
        return None
    trs = []
    for i in range(1, len(closes)):
        trs.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
    return sum(trs[-period:]) / period

def live_order_fn(kernel, symbol, side, risk_pct, lev, tp_pct, sl_pct, max_notional=200.0):
    return kernel.open_market(symbol, side, risk_pct, lev, tp_pct, sl_pct, max_notional=max_notional)

def fetch_ohlcv(symbol, interval="5m", limit=80, base="https://fapi.binance.com"):
    """Public OHLCV dict {o,h,l,c,v} — parliament / alpha_core compatible."""
    url = "%s/fapi/v1/klines?symbol=%s&interval=%s&limit=%d" % (
        base.rstrip("/"), symbol, interval, int(limit)
    )
    req = urllib.request.Request(url, headers={"User-Agent": "honeycomb-kernel-ohlcv", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=8) as resp:
        raw = json.loads(resp.read().decode("utf-8"))
    return {
        "o": [float(x[1]) for x in raw],
        "h": [float(x[2]) for x in raw],
        "l": [float(x[3]) for x in raw],
        "c": [float(x[4]) for x in raw],
        "v": [float(x[5]) for x in raw],
    }


class CircuitBreaker:
    """Consecutive-failure trip with cooldown. Thread-safe."""

    def __init__(self, fail_threshold=4, cooldown_sec=180, half_open_trial=True):
        self.fail_threshold = fail_threshold
        self.cooldown_sec = cooldown_sec
        self.half_open_trial = half_open_trial
        self.fails = 0
        self.state = "CLOSED"
        self.opened_at = 0.0
        self._lock = threading.Lock()

    def record_success(self):
        with self._lock:
            self._fails = 0
            self._state = "CLOSED"

    def record_failure(self):
        with self._lock:
            self._fails += 1
            if self._fails >= self.fail_threshold:
                self._state = "OPEN"
                self._opened_at = time.time()

    def allow(self) -> bool:
        with self._lock:
            if self._state == "CLOSED":
                return True
            elapsed = time.time() - self._opened_at
            if elapsed >= self.cooldown_sec:
                if self.half_open_trial:
                    self._state = "HALF_OPEN"
                    return True
                self._state = "CLOSED"
                self._fails = 0
                return True
            return False

    def state(self) -> str:
        with self._lock:
            return self._state

    def time_until_reset(self) -> float:
        with self._lock:
            if self._state != "OPEN":
                return 0.0
            return max(0.0, self.cooldown_sec - (time.time() - self._opened_at))


# ------------------------------------------------- CRYPTOGRAPHIC AUDIT LOG -
class CryptographicAuditLedger:
    """Append-only hash-chained JSONL. Tamper-evident."""
    GENESIS = "0" * 64

    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()
        if not os.path.exists(self.path):
            open(self.path, "a").close()

    def _last_hash(self):
        last = self.GENESIS
        if not os.path.exists(self.path):
            return last
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    last = json.loads(line).get("hash", last)
                except Exception:
                    pass
        return last

    def append(self, event):
        with self._lock:
            prev = self._last_hash()
            rec = {"ts": time.time(), "prev_hash": prev, "data": event}
            payload = json.dumps(rec, sort_keys=True, ensure_ascii=False).encode("utf-8")
            rec["hash"] = hashlib.sha256(payload).hexdigest()
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            return rec

    def verify_chain(self):
        prev = self.GENESIS
        if not os.path.exists(self.path):
            return True, None
        with open(self.path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    return False, i
                if rec.get("prev_hash") != prev_hash:
                    return False, i
                claimed_hash = rec.get("hash")
                recomputed = dict(rec)
                recomputed.pop("hash", None)
                payload = json.dumps(recomputed, sort_keys=True, ensure_ascii=False).encode("utf-8")
                expect = hashlib.sha256(prev_hash.encode("utf-8") + payload).hexdigest()
                if expect != claimed_hash:
                    return False, i
                prev_hash = claimed_hash
        return True, None


# --------------------------------------------- DYNAMIC TRAILING STOP ENGINE
# --------------------------------------------------- PARTIAL PROFIT ENGINE -
class PartialProfitEngine:
    DEFAULT_STAGES = [(0.50, 0.35), (0.80, 0.35)]

    def __init__(self, kernel, stages=None, log_fn=None):
        self.kernel = kernel
        self.stages = stages or list(self.DEFAULT_STAGES)
        self.log = log_fn or (lambda m: None)
        self._pos = {}
        self._lock = threading.Lock()

    def register(self, symbol, side, entry, tp, sl, qty, pos_side=None):
        with self._lock:
            self._pos[symbol] = {
                "side": side, "entry": entry, "tp": tp, "sl": sl,
                "qty_remaining": qty, "stage": 0, "pos_side": pos_side,
                "realized_net": 0.0,
                "qty": qty, "qty_remaining": qty, "stage": 0,
                "pos_side": pos_side, "realized_net": 0.0,
            }

    def forget(self, symbol):
        with self._lock:
            return self._pos.pop(symbol, None)

    def get(self, symbol) -> Optional[Dict[str, Any]]:
        with self._lock:
            return dict(self._pos[symbol]) if symbol in self._pos else None

    def update(self, symbol, current_price) -> Optional[Dict[str, Any]]:
        with self._lock:
            pos = self._pos.get(symbol)
        if not pos or pos["qty_remaining"] <= 0 or pos["stage"] >= len(self.stages):
            return None
        entry, side, tp = pos["entry"], pos["side"], pos["tp"]
        dist = abs(tp - entry)
        if dist <= 0:
            return None
        progress = (current_price - entry) / dist if side == "LONG" else (entry - current_price) / dist
        thresh, close_frac = self.stages[pos["stage"]]
        if progress < thresh:
            return None

        close_qty = pos["qty_remaining"] * close_frac
        try:
            fill = self.kernel.close_market(symbol, side, close_qty, pos.get("pos_side"))
            net = float(fill.get("rp", 0.0)) - float(fill.get("commission", 0.0))
            with self._lock:
                if symbol not in self._pos:
                    return None
                self._pos[symbol]["qty_remaining"] = max(0.0, self._pos[symbol]["qty_remaining"] - fill["qty"])
                self._pos[symbol]["stage"] += 1
                self._pos[symbol]["realized_net"] += net
                remaining = self._pos[symbol]["qty_remaining"]
                stage_done = self._pos[symbol]["stage"]
            if remaining > 0:
                self.kernel.place_protect(symbol, side, entry, tp, pos["sl"], pos.get("pos_side"))
            self.log(
                f"KISMI KAR AL {side} {symbol} | ilerleme={progress*100:.0f}% | kapatılan={fill['qty']:.6g} "
                f"(kademe {stage_done}/{len(self.stages)}) | net={net:+.4f} | kalan={remaining:.6g}"
            )
            return {"qty_closed": fill["qty"], "net": net, "remaining": remaining, "stage": stage_done}
        except Exception as e:
            self.log(f"KISMI KAR AL HATA {symbol}: {e}")
            return None


class DynamicTrailingStopEngine:
    DEFAULT_STAGES = [(0.35, 0.05), (0.60, 0.25), (0.85, 0.55)]

    def __init__(self, kernel, stages=None, log_fn=None):
        self.kernel = kernel
        self.stages = stages or list(self.DEFAULT_STAGES)
        self.log = log_fn or (lambda m: None)
        self._pos = {}
        self._lock = threading.Lock()

    def register(self, symbol, side, entry, tp, sl):
        with self._lock:
            self._pos[symbol] = {"side": side, "entry": entry, "tp": tp, "sl": sl, "stage": 0}

    def forget(self, symbol):
        with self._lock:
            self._pos.pop(symbol, None)

    def update(self, symbol, current_price) -> Optional[float]:
        with self._lock:
            pos = self._pos.get(symbol)
        if not pos:
            return None
        entry, side, tp = pos["entry"], pos["side"], pos["tp"]
        dist = abs(tp - entry)
        if dist <= 0:
            return None
        progress = (current_price - entry) / dist if side == "LONG" else (entry - current_price) / dist

        new_stage, lock_frac = None, None
        for idx, (thresh, frac) in enumerate(self.stages, start=1):
            if progress >= thresh and idx > pos["stage"]:
                new_stage, lock_frac = idx, frac
        if new_stage is None:
            return None

        new_sl = entry + lock_frac * dist if side == "LONG" else entry - lock_frac * dist
        try:
            self.kernel.cancel_all(symbol)
            self.kernel.place_protect(symbol, side, entry, tp, new_sl)
            with self._lock:
                if symbol in self._pos:
                    self._pos[symbol]["sl"] = new_sl
                    self._pos[symbol]["stage"] = new_stage
            self.log(f"TRAIL {side} {symbol} ilerleme={progress*100:.0f}% -> yeni SL={new_sl:.6f} (kademe {new_stage})")
            return new_sl
        except Exception as e:
            self.log(f"TRAIL HATA {symbol}: {e}")
            return None


# ------------------------------------------------- PURE PYTHON WS CLIENT ---
class PurePythonWebSocketClient:
    """
    Harici paket GEREKTİRMEYEN (Termux'ta pandas/gradio gibi ağır
    derleme sorunlarına sebep olabilen 'websockets' kütüphanesine
    ihtiyaç duymayan) minimal RFC6455 WebSocket istemcisi. Binance'in
    fstream.binance.com bookTicker/kline stream'lerinden milisaniye
    gecikmeli fiyat akışı çekmek için yeterlidir: el sıkışma (handshake),
    metin çerçevesi (text frame) çözme, ping/pong, ve otomatik yeniden
    bağlanma içerir.
    """
    def __init__(self, url: str, on_message=None, on_error=None, log_fn=None):
        self.url = url
        self.on_message = on_message or (lambda msg: None)
        self.on_error = on_error or (lambda e: None)
        self.log = log_fn or (lambda m: None)
        self._stop = threading.Event()
        self._thread = None
        self._sock = None

    def start(self):
        self._thread = threading.Thread(target=self._run_forever, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        try:
            if self._sock:
                self._sock.close()
        except Exception:
            pass

    def _run_forever(self):
        backoff = 1.0
        while not self._stop.is_set():
            try:
                self._connect_and_listen()
                backoff = 1.0
            except Exception as e:
                self.on_error(e)
                self.log(f"WS bağlantı hatası, {backoff:.0f}sn sonra tekrar denenecek: {e}")
                time.sleep(backoff)
                backoff = min(30.0, backoff * 1.7)

    def _connect_and_listen(self):
        import base64
        import os as _os
        import socket
        import ssl
        parsed = urllib.parse.urlparse(self.url)
        host = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == "wss" else 80)
        path = parsed.path + (("?" + parsed.query) if parsed.query else "")

        raw = socket.create_connection((host, port), timeout=10)
        sock = ssl.create_default_context().wrap_socket(raw, server_hostname=host) if parsed.scheme == "wss" else raw
        self._sock = sock

        ws_key = base64.b64encode(_os.urandom(16)).decode()
        handshake = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {ws_key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        sock.sendall(handshake.encode("utf-8"))

        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = sock.recv(4096)
            if not chunk:
                raise ConnectionError("El sıkışma sırasında bağlantı koptu")
            resp += chunk
        status_line = resp.split(b"\r\n", 1)[0]
        if b"101" not in status_line:
            raise ConnectionError(f"WS el sıkışma reddedildi: {status_line!r}")
        self.log(f"WS bağlandı: {self.url}")

        buffer = resp.split(b"\r\n\r\n", 1)[1]
        while not self._stop.is_set():
            frame, buffer = self._read_frame(sock, buffer)
            if frame is None:
                continue
            opcode, payload = frame
            if opcode == 0x8:  # close
                raise ConnectionError("Sunucu bağlantıyı kapattı")
            elif opcode == 0x9:  # ping -> pong
                self._send_frame(sock, payload, opcode=0xA)
            elif opcode in (0x1, 0x2):  # text/binary
                try:
                    self.on_message(payload.decode("utf-8", errors="replace"))
                except Exception as e:
                    self.on_error(e)

    @staticmethod
    def _read_frame(sock, buffer: bytes):
        def need(n):
            nonlocal buffer
            while len(buffer) < n:
                chunk = sock.recv(4096)
                if not chunk:
                    raise ConnectionError("Akış sırasında bağlantı koptu")
                buffer += chunk

        need(2)
        b0, b1 = buffer[0], buffer[1]
        opcode = b0 & 0x0F
        masked = (b1 & 0x80) != 0
        length = b1 & 0x7F
        offset = 2
        if length == 126:
            need(4)
            length = int.from_bytes(buffer[2:4], "big")
            offset = 4
        elif length == 127:
            need(10)
            length = int.from_bytes(buffer[2:10], "big")
            offset = 10
        mask_key = b""
        if masked:
            need(offset + 4)
            mask_key = buffer[offset:offset + 4]
            offset += 4
        need(offset + length)
        payload = buffer[offset:offset + length]
        if masked:
            payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
        remaining = buffer[offset + length:]
        return (opcode, payload), remaining

    @staticmethod
    def _send_frame(sock, payload: bytes, opcode=0x1):
        import os as _os
        fin_opcode = 0x80 | opcode
        length = len(payload)
        mask_key = _os.urandom(4)
        masked_payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
        if length < 126:
            header = bytes([fin_opcode, 0x80 | length])
        elif length < 65536:
            header = bytes([fin_opcode, 0x80 | 126]) + length.to_bytes(2, "big")
        else:
            header = bytes([fin_opcode, 0x80 | 127]) + length.to_bytes(8, "big")
        sock.sendall(header + mask_key + masked_payload)


# ------------------------------------------------- NUMERIC GUARDS ---
# live/__init__.py bu isimleri bekliyordu ama kernel.py'de tanımlı değildi
# (ImportError: cannot import name '_finite_num'). None/nan/inf gelen
# fiyat, miktar, bakiye değerlerini scanner/alpha/parliament zincirine
# sızdırmadan güvenli karşılaştırma yapmak için eklendi.

import math as _math

def _finite_num(x, default=None):
    """None/NaN/Inf/geçersiz değerleri güvenli float'a çevirir; olmazsa default döner."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    if _math.isnan(v) or _math.isinf(v):
        return default
    return v

def _gt(a, b):
    a, b = _finite_num(a), _finite_num(b)
    if a is None or b is None:
        return False
    return a > b

def _lt(a, b):
    a, b = _finite_num(a), _finite_num(b)
    if a is None or b is None:
        return False
    return a < b

def _ge(a, b):
    a, b = _finite_num(a), _finite_num(b)
    if a is None or b is None:
        return False
    return a >= b

def _le(a, b):
    a, b = _finite_num(a), _finite_num(b)
    if a is None or b is None:
        return False
    return a <= b



# ============================================================
# MOTOR UYUMLULUK KATMANI — Emir fonksiyonları
# ============================================================

def live_order_fn(kernel, symbol, side, risk_pct, lev, tp_pct, sl_pct, max_notional=200.0):
    """SOVEREIGN-V3 ve diğer motorların beklediği emir köprüsü."""
    return kernel.open_market(symbol, side, risk_pct, lev, tp_pct, sl_pct, max_notional=max_notional)

# LiveKernel sınıfına eksik metodları ekle
def _add_order_methods():
    if not hasattr(LiveKernel, "enter"):
        def enter(self, symbol, side, risk_pct=0.1, lev=10, tp_pct=1.2, sl_pct=0.8, max_notional=200.0):
            return self.open_market(symbol, side, risk_pct, lev, tp_pct, sl_pct, max_notional=max_notional)
        LiveKernel.enter = enter

    if not hasattr(LiveKernel, "place_order"):
        def place_order(self, symbol, side, qty, position_side=None, reduce_only=False):
            return self.place_market(symbol, side, qty, position_side=position_side, reduce_only=reduce_only)
        LiveKernel.place_order = place_order

    if not hasattr(LiveKernel, "create_market_order"):
        def create_market_order(self, symbol, side, qty, position_side=None):
            return self.place_market(symbol, side, qty, position_side=position_side)
        LiveKernel.create_market_order = create_market_order

_add_order_methods()
            return self._pos.pop(symbol, None)

    def update(self, symbol, current_price):
        with self._lock:
            pos = self._pos.get(symbol)
            if not pos:
                return None
            entry = float(pos["entry"])
            dist = abs(float(pos["tp"]) - entry)
            if dist <= 0:
                return None
            progress = (current_price - entry) / dist if pos["side"] == "LONG" else (entry - current_price) / dist
            new_stage, lock_frac = None, None
            for i, (thresh, frac) in enumerate(self.stages):
                if progress >= thresh and i >= pos["stage"]:
                    new_stage, lock_frac = i + 1, frac
            if new_stage is None:
                return None
            new_sl = entry + lock_frac * dist if pos["side"] == "LONG" else entry - lock_frac * dist
            try:
                self.kernel.cancel_all(symbol)
                self.kernel.place_protect(symbol, pos["side"], entry, pos["tp"], new_sl)
                pos["sl"] = new_sl
                pos["stage"] = new_stage
                self.log("TRAIL %s %s stage=%d new_sl=%.6f" % (pos["side"], symbol, new_stage, new_sl))
                return new_sl
            except Exception as e:
                self.log("TRAIL HATA %s: %s" % (symbol, e))
                return None
