#!/data/data/com.termux/files/usr/bin/python3
# -*- coding: utf-8 -*-
"""Honeycomb Live Kernel — dual-venue HMAC. No ghost fills. Exchange protect. Fill ledger."""
from __future__ import annotations
import fcntl, hashlib, hmac, json, os, threading, time, urllib.error, urllib.parse, urllib.request
from typing import Any, Dict, List, Optional, Tuple

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
        self.path = path or "/tmp/honeycomb_sf.lock"
        self.fd = None
    def acquire(self, timeout=8.0):
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
        self.key = api_key or self.env.get("BINANCE_API_KEY") or self.env.get("API_KEY") or ""
        self.secret = (api_secret or self.env.get("BINANCE_API_SECRET") or self.env.get("BINANCE_SECRET") or self.env.get("API_SECRET") or "").encode()
        self.recv = int(self.env.get("RECV_WINDOW", "10000"))
        self.bucket = TokenBucket()
        self.flock = SingleFlight()
        self._off = 0
        self._filters: Dict[str, Dict] = {}
        self._stale_until = 0.0
        self.log = log_fn or (lambda m: print(time.strftime("%H:%M:%S") + " [K] " + str(m), flush=True))
        self.sync_time()

    def sync_time(self):
        try:
            data = self._http("GET", self.v["time"], {}, signed=False, weight=1)
            server = int(data["serverTime"])
            self._off = server - int(time.time() * 1000)
        except Exception as e:
            self.log("time sync fail: %s" % e)

    def _sign(self, params: Dict) -> str:
        qs = urllib.parse.urlencode(params, doseq=True)
        sig = hmac.new(self.secret, qs.encode(), hashlib.sha256).hexdigest()
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
            body = urllib.parse.urlencode(params, doseq=True)
        url = self.v["rest"] + path + (("?" + body) if method == "GET" and body else "")
        data = body.encode() if method != "GET" else None
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
        params = {"symbol": symbol, "side": side, "type": "MARKET", "quantity": q}
        if position_side:
            params["positionSide"] = position_side
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
        """Source of truth: userTrades. Never invent avg from book."""
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

def atr(closes, period=14):
    if len(closes) < period + 1: return None
    trs = [abs(closes[i] - closes[i - 1]) for i in range(1, len(closes))]
    return sum(trs[-period:]) / period
