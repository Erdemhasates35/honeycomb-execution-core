#!/data/data/com.termux/files/usr/bin/python3
# -*- coding: utf-8 -*-
"""HONEYCOMB LIVE KERNEL — single source of truth for Binance Futures execution.

Design invariants:
- LIVE execution only; no paper/testnet endpoint is exposed by this kernel.
- Exchange metadata is authoritative; synthetic filters are forbidden.
- Decimal tick/step arithmetic; no binary-float order rounding.
- Position mode, leverage, margin mode and fills are verified from Binance.
- No synthetic zero commission/PnL is ever returned as a reconciled fill.
- COIN-M quantity uses exchange contractSize.
- Protection orders are exchange-native MARK_PRICE close-position orders.
"""
from __future__ import annotations

import fcntl, hashlib, hmac, json, math, os, sys, threading, time
import urllib.error, urllib.parse, urllib.request
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_UP
from typing import Any, Dict, List, Optional, Tuple

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

VENUES = {
    "usdt": {
        "rest": "https://fapi.binance.com",
        "time": "/fapi/v1/time", "order": "/fapi/v1/order",
        "balance": "/fapi/v2/balance", "position": "/fapi/v2/positionRisk",
        "account": "/fapi/v2/account", "trades": "/fapi/v1/userTrades",
        "premium": "/fapi/v1/premiumIndex", "exchangeInfo": "/fapi/v1/exchangeInfo",
        "leverage": "/fapi/v1/leverage", "dual": "/fapi/v1/positionSide/dual",
        "allOpen": "/fapi/v1/allOpenOrders", "bookTicker": "/fapi/v1/ticker/bookTicker",
        "klines": "/fapi/v1/klines", "marginType": "/fapi/v1/marginType",
        "commission": "/fapi/v1/commissionRate", "bracket": "/fapi/v1/leverageBracket",
    },
    "coin": {
        "rest": "https://dapi.binance.com",
        "time": "/dapi/v1/time", "order": "/dapi/v1/order",
        "balance": "/dapi/v1/balance", "position": "/dapi/v1/positionRisk",
        "account": "/dapi/v1/account", "trades": "/dapi/v1/userTrades",
        "premium": "/dapi/v1/premiumIndex", "exchangeInfo": "/dapi/v1/exchangeInfo",
        "leverage": "/dapi/v1/leverage", "dual": "/dapi/v1/positionSide/dual",
        "allOpen": "/dapi/v1/allOpenOrders", "bookTicker": "/dapi/v1/ticker/bookTicker",
        "klines": "/dapi/v1/klines", "marginType": "/dapi/v1/marginType",
        "commission": "/dapi/v1/commissionRate", "bracket": "/dapi/v1/leverageBracket",
    },
}

def load_env(path: Optional[str] = None) -> Dict[str, str]:
    p = path or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    out: Dict[str, str] = {}
    if os.path.exists(p):
        with open(p, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    out[k.strip()] = v.strip().split("#", 1)[0].strip()
    for k, v in os.environ.items():
        out.setdefault(k, v)
    return out

def finite(x: Any) -> float:
    try:
        v = float(x)
        if not math.isfinite(v):
            raise ValueError("non-finite")
        return v
    except (TypeError, ValueError):
        raise ValueError("non-finite numeric value")

def _D(x: Any) -> Decimal:
    try:
        d = Decimal(str(x))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("invalid decimal")
    if not d.is_finite():
        raise ValueError("non-finite decimal")
    return d

class TokenBucket:
    def __init__(self, wpm: float = 1800.0, orders10s: float = 200.0):
        self.wcap, self.ocap = float(wpm), float(orders10s)
        self.w, self.o, self.t = self.wcap, self.ocap, time.time()
        self.lock = threading.Lock()

    def take(self, weight: float = 1.0, is_order: bool = False) -> None:
        weight = max(1.0, float(weight))
        while True:
            with self.lock:
                now = time.time()
                dt = max(0.0, now - self.t)
                self.t = now
                self.w = min(self.wcap, self.w + dt * self.wcap / 60.0)
                self.o = min(self.ocap, self.o + dt * self.ocap / 10.0)
                need_w = max(0.0, weight - self.w)
                need_o = max(0.0, 1.0 - self.o) if is_order else 0.0
                if need_w <= 0 and need_o <= 0:
                    self.w -= weight
                    if is_order:
                        self.o -= 1.0
                    return
                sleep_for = max(
                    need_w / (self.wcap / 60.0),
                    need_o / (self.ocap / 10.0),
                    0.05,
                )
            time.sleep(min(sleep_for, 5.0))

class SingleFlight:
    def __init__(self, path: Optional[str] = None):
        self.path = path or os.path.expanduser("~/.honeycomb_runtime/honeycomb_sf.lock")
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.fd = None

    def acquire(self, timeout: float = 8.0, blocking: bool = True) -> bool:
        self.fd = open(self.path, "a+")
        start = time.time()
        while True:
            try:
                flags = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
                fcntl.flock(self.fd, flags)
                return True
            except BlockingIOError:
                if not blocking or time.time() - start >= timeout:
                    self.release()
                    return False
                time.sleep(0.05)

    def release(self) -> None:
        if self.fd is not None:
            try: fcntl.flock(self.fd, fcntl.LOCK_UN)
            except Exception: pass
            try: self.fd.close()
            except Exception: pass
            self.fd = None

class LiveKernel:
    def __init__(self, venue: str = "usdt", api_key: Optional[str] = None,
                 api_secret: Optional[str] = None, env: Optional[Dict[str, str]] = None,
                 log_fn=None):
        self.env = env or load_env()
        self.venue = str(venue).lower()
        if self.venue not in VENUES:
            raise ValueError("unsupported venue")
        self.v = VENUES[self.venue]
        self.key = (api_key or self.env.get("BINANCE_API_KEY") or self.env.get("API_KEY") or "").strip()
        secret = api_secret or self.env.get("BINANCE_SECRET_KEY") or self.env.get("BINANCE_API_SECRET") or self.env.get("BINANCE_SECRET") or self.env.get("API_SECRET") or ""
        self.secret = str(secret).strip().encode()
        if not self.key or not self.secret:
            raise RuntimeError("Binance API credentials unavailable")
        self.recv = int(self.env.get("RECV_WINDOW", "10000"))
        self.bucket = TokenBucket()
        self.flock = SingleFlight()
        self._offset_ms = 0
        self._filters: Dict[str, Dict[str, float]] = {}
        self._dual: Optional[bool] = None
        self._margin_type: Dict[str, str] = {}
        self._halt_until = 0.0
        self.log = log_fn or (lambda m: print(time.strftime("%H:%M:%S") + " [KERNEL] " + str(m), flush=True))
        self.sync_time()

    @property
    def hedge_mode(self) -> bool:
        return bool(self.position_mode())

    @property
    def margin_type(self) -> str:
        return "ISOLATED"

    def sync_time(self) -> int:
        data = self._http("GET", self.v["time"], signed=False, weight=1)
        self._offset_ms = int(data["serverTime"]) - int(time.time() * 1000)
        return self._offset_ms

    def _signed_query(self, params: Dict[str, Any]) -> str:
        clean = [(k, str(v)) for k, v in params.items() if v is not None]
        qs = urllib.parse.urlencode(clean, doseq=True)
        sig = hmac.new(self.secret, qs.encode(), hashlib.sha256).hexdigest()
        return qs + "&signature=" + sig

    def _http(self, method: str, path: str, params: Optional[Dict[str, Any]] = None,
              signed: bool = False, weight: int = 1, is_order: bool = False,
              retries: int = 3) -> Any:
        if time.time() < self._halt_until:
            raise RuntimeError("execution halted after transport failure")
        self.bucket.take(weight, is_order)
        base = dict(params or {})
        last = None
        for attempt in range(max(1, retries)):
            q = dict(base)
            if signed:
                q["timestamp"] = int(time.time() * 1000) + self._offset_ms
                q["recvWindow"] = self.recv
                body = self._signed_query(q)
            else:
                body = urllib.parse.urlencode([(k, str(v)) for k, v in q.items() if v is not None], doseq=True)
            url = self.v["rest"] + path + (("?" + body) if method == "GET" and body else "")
            data = None if method == "GET" else body.encode()
            req = urllib.request.Request(
                url, data=data,
                headers={"X-MBX-APIKEY": self.key, "Content-Type": "application/x-www-form-urlencoded"},
                method=method,
            )
            try:
                with urllib.request.urlopen(req, timeout=12) as resp:
                    raw = resp.read().decode()
                    return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as exc:
                raw = exc.read().decode() if exc.fp else str(exc)
                try: err = json.loads(raw)
                except Exception: err = {"msg": raw}
                code = err.get("code")
                if code in (-1021, -1022) and attempt + 1 < retries:
                    self.sync_time()
                    time.sleep(0.15 * (attempt + 1))
                    continue
                if code == -1003:
                    self._halt_until = time.time() + 30
                    raise RuntimeError("Binance rate-limit response -1003")
                if code == -2015:
                    raise RuntimeError("Binance API key/IP permission rejected (-2015)")
                raise RuntimeError("HTTP %s: %s" % (exc.code, err))
            except (urllib.error.URLError, TimeoutError, ConnectionResetError, OSError) as exc:
                last = exc
                if attempt + 1 < retries:
                    time.sleep(0.3 * (attempt + 1))
                    continue
                self._halt_until = time.time() + 15
                raise RuntimeError("Binance transport failure: %s" % exc)
        raise RuntimeError("request failed: %s" % last)

    def _parse_filters(self, symbol: str, row: Dict[str, Any]) -> Dict[str, float]:
        f: Dict[str, float] = {}
        for x in row.get("filters", []):
            typ = x.get("filterType")
            if typ == "LOT_SIZE":
                f["stepSize"] = finite(x.get("stepSize"))
                f["minQty"] = finite(x.get("minQty"))
                f["maxQty"] = finite(x.get("maxQty"))
            elif typ in ("MIN_NOTIONAL", "NOTIONAL"):
                f["minNotional"] = finite(x.get("notional", x.get("minNotional", 0)))
            elif typ == "PRICE_FILTER":
                f["tickSize"] = finite(x.get("tickSize"))
        if min(f.get("stepSize", 0), f.get("minQty", 0), f.get("tickSize", 0)) <= 0:
            raise RuntimeError("incomplete exchange metadata for " + symbol)
        if self.venue == "coin":
            f["contractSize"] = finite(row.get("contractSize"))
            if f["contractSize"] <= 0:
                raise RuntimeError("missing contractSize for " + symbol)
        f.setdefault("minNotional", 0.0)
        return f

    def load_exchange_info(self, symbols: Optional[List[str]] = None) -> Dict[str, Dict[str, float]]:
        wanted = {s.upper() for s in symbols} if symbols else None
        data = self._http("GET", self.v["exchangeInfo"], signed=False, weight=10)
        loaded = 0
        for row in data.get("symbols", []):
            sym = str(row.get("symbol") or "").upper()
            if not sym or (wanted is not None and sym not in wanted):
                continue
            try:
                self._filters[sym] = self._parse_filters(sym, row)
                loaded += 1
            except Exception as exc:
                self.log("metadata rejected %s: %s" % (sym, exc))
        if wanted and not wanted.issubset(self._filters):
            missing = sorted(wanted - set(self._filters))
            raise RuntimeError("exchange metadata missing: " + ",".join(missing))
        return self._filters

    def get_filters(self, symbol: str) -> Dict[str, float]:
        symbol = symbol.upper()
        if symbol not in self._filters:
            self.load_exchange_info([symbol])
        return self._filters[symbol]

    @staticmethod
    def round_step(qty: Any, step: Any, rounding=ROUND_DOWN) -> float:
        q, s = _D(qty), _D(step)
        if s <= 0: raise ValueError("invalid quantity step")
        return float((q / s).to_integral_value(rounding=rounding) * s)

    @staticmethod
    def round_price(price: Any, tick: Any, direction: str) -> float:
        p, t = _D(price), _D(tick)
        if p <= 0 or t <= 0: raise ValueError("invalid price/tick")
        mode = ROUND_DOWN if direction.upper() == "DOWN" else ROUND_UP
        return float((p / t).to_integral_value(rounding=mode) * t)

    def position_mode(self, dual: Optional[bool] = None) -> bool:
        if dual is None:
            data = self._http("GET", self.v["dual"], signed=True, weight=1)
            self._dual = bool(data.get("dualSidePosition"))
            return self._dual
        self._http("POST", self.v["dual"], {"dualSidePosition": "true" if dual else "false"},
                   signed=True, weight=1, is_order=True)
        self._dual = bool(dual)
        return self._dual

    def set_margin(self, symbol: str, isolated: bool = True) -> str:
        desired = "ISOLATED" if isolated else "CROSSED"
        try:
            self._http("POST", self.v["marginType"], {"symbol": symbol, "marginType": desired},
                       signed=True, weight=1, is_order=True)
        except Exception as exc:
            if "No need" not in str(exc) and "already" not in str(exc).lower():
                raise
        self._margin_type[symbol] = desired
        return desired

    def set_margin_type(self, symbol: str, isolated: bool = True) -> str:
        return self.set_margin(symbol, isolated)

    def max_leverage_for_notional(self, symbol: str, notional: float = 0.0) -> int:
        data = self._http("GET", self.v["bracket"], {"symbol": symbol}, signed=True, weight=1)
        rows = data if isinstance(data, list) else []
        if rows and isinstance(rows[0], dict) and "brackets" in rows[0]:
            rows = rows[0]["brackets"]
        if not rows:
            raise RuntimeError("leverage bracket unavailable for " + symbol)
        n = max(0.0, finite(notional))
        eligible = [r for r in rows if n <= finite(r.get("notionalCap", float("inf")))]
        row = eligible[0] if eligible else rows[-1]
        return max(1, int(float(row.get("initialLeverage") or row.get("leverage") or 1)))

    def set_leverage(self, symbol: str, leverage: int) -> int:
        requested = int(leverage)
        if requested < 1:
            raise ValueError("leverage must be >= 1")
        self._http("POST", self.v["leverage"], {"symbol": symbol, "leverage": requested},
                   signed=True, weight=1, is_order=True)
        rows = self._http("GET", self.v["position"], {"symbol": symbol}, signed=True, weight=5)
        rows = rows if isinstance(rows, list) else []
        same = [p for p in rows if str(p.get("symbol")) == symbol]
        if not same or same[0].get("leverage") is None:
            raise RuntimeError("leverage verification unavailable for " + symbol)
        actual = int(float(same[0]["leverage"]))
        if actual != requested:
            raise RuntimeError("leverage mismatch %s requested=%s actual=%s" % (symbol, requested, actual))
        return actual

    def book(self, symbol: str) -> Tuple[float, float, float]:
        d = self._http("GET", self.v["bookTicker"], {"symbol": symbol}, signed=False, weight=2)
        bid, ask = finite(d.get("bidPrice")), finite(d.get("askPrice"))
        if bid <= 0 or ask <= 0 or ask < bid:
            raise RuntimeError("invalid/stale book " + symbol)
        return bid, ask, (bid + ask) / 2.0

    def mark(self, symbol: str) -> float:
        d = self._http("GET", self.v["premium"], {"symbol": symbol}, signed=False, weight=1)
        px = finite(d.get("markPrice") or d.get("indexPrice"))
        if px <= 0:
            raise RuntimeError("invalid mark price " + symbol)
        return px

    def price(self, symbol: str) -> float:
        return self.mark(symbol)

    def klines(self, symbol: str, interval: str = "1m", limit: int = 200) -> Tuple[List[float], List[float]]:
        d = self._http("GET", self.v["klines"], {"symbol": symbol, "interval": interval, "limit": min(1500, max(10, int(limit)))}, signed=False, weight=2)
        closes = [finite(x[4]) for x in d]
        volumes = [finite(x[5]) for x in d]
        if len(closes) < 10 or any(x <= 0 for x in closes):
            raise RuntimeError("insufficient/invalid klines " + symbol)
        return closes, volumes

    def balance_usdt(self) -> float:
        data = self._http("GET", self.v["balance"], signed=True, weight=5)
        if self.venue == "usdt":
            row = next((x for x in data if str(x.get("asset")).upper() == "USDT"), None)
            if row is None:
                raise RuntimeError("USDT balance row unavailable")
            return max(0.0, finite(row.get("availableBalance", row.get("balance"))))
        total = 0.0
        for row in data:
            asset = str(row.get("asset") or "").upper()
            amount = max(0.0, finite(row.get("availableBalance", row.get("balance"))))
            if amount <= 0: continue
            if asset == "USD":
                total += amount
                continue
            sym = asset + "USD_PERP"
            try: total += amount * self.mark(sym)
            except Exception: continue
        if total <= 0:
            raise RuntimeError("COIN-M USD-equity unavailable")
        return total

    def balance(self) -> float:
        return self.balance_usdt()

    def position_rows(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        p = {"symbol": symbol} if symbol else {}
        data = self._http("GET", self.v["position"], p, signed=True, weight=5)
        return [x for x in (data if isinstance(data, list) else []) if symbol is None or x.get("symbol") == symbol]

    def position_amt(self, symbol: str, side: Optional[str] = None) -> float:
        rows = self.position_rows(symbol)
        total = 0.0
        for p in rows:
            amt = finite(p.get("positionAmt", 0))
            if side is None:
                total += abs(amt)
            elif side.upper() == "LONG" and amt > 0:
                return abs(amt)
            elif side.upper() == "SHORT" and amt < 0:
                return abs(amt)
        return total if side is None else 0.0

    def _order_qty(self, symbol: str, notional: float, entry: float) -> float:
        f = self.get_filters(symbol)
        n = finite(notional)
        if n <= 0 or entry <= 0:
            raise ValueError("invalid notional/entry")
        if self.venue == "coin":
            qty = n / f["contractSize"]
        else:
            qty = n / entry
        qty = self.round_step(qty, f["stepSize"])
        if self.venue == "coin":
            qty = max(1.0, qty)
        if qty < f["minQty"]:
            raise RuntimeError("quantity below exchange minimum")
        if f.get("maxQty", 0) > 0 and qty > f["maxQty"]:
            qty = self.round_step(f["maxQty"], f["stepSize"])
        if f.get("minNotional", 0) > 0:
            actual_notional = qty * (f["contractSize"] if self.venue == "coin" else entry)
            if actual_notional < f["minNotional"]:
                raise RuntimeError("notional below exchange minimum")
        return qty

    def place_market(self, symbol: str, side: str, qty: float,
                     position_side: Optional[str] = None, reduce_only: bool = False) -> Dict[str, Any]:
        f = self.get_filters(symbol)
        q = self.round_step(qty, f["stepSize"])
        if q < f["minQty"]:
            raise RuntimeError("quantity below exchange minimum")
        params: Dict[str, Any] = {"symbol": symbol, "side": side.upper(), "type": "MARKET", "quantity": q}
        if position_side in ("LONG", "SHORT"):
            params["positionSide"] = position_side
        elif self.position_mode():
            raise RuntimeError("hedge mode requires LONG/SHORT positionSide")
        elif reduce_only:
            params["reduceOnly"] = "true"
        return self._http("POST", self.v["order"], params, signed=True, weight=1, is_order=True)

    def place_protect(self, symbol: str, side: str, entry: float, tp: float, sl: float,
                      position_side: Optional[str] = None) -> Dict[str, Any]:
        f = self.get_filters(symbol)
        close_side = "SELL" if side.upper() == "LONG" else "BUY"
        direction = "DOWN" if side.upper() == "LONG" else "UP"
        tp_px = self.round_price(tp, f["tickSize"], direction)
        sl_px = self.round_price(sl, f["tickSize"], direction)
        if side.upper() == "LONG" and not (sl_px < entry < tp_px):
            raise RuntimeError("invalid LONG protection surface")
        if side.upper() == "SHORT" and not (tp_px < entry < sl_px):
            raise RuntimeError("invalid SHORT protection surface")
        placed: List[str] = []
        try:
            for typ, stop in (("TAKE_PROFIT_MARKET", tp_px), ("STOP_MARKET", sl_px)):
                params: Dict[str, Any] = {
                    "symbol": symbol, "side": close_side, "type": typ,
                    "stopPrice": stop, "closePosition": "true", "workingType": "MARK_PRICE",
                }
                if position_side in ("LONG", "SHORT"):
                    params["positionSide"] = position_side
                elif self.position_mode():
                    raise RuntimeError("hedge mode protection requires positionSide")
                self._http("POST", self.v["order"], params, signed=True, weight=1, is_order=True)
                placed.append(typ)
        except Exception:
            try: self.cancel_all(symbol)
            except Exception: pass
            raise
        return {"tp": tp_px, "sl": sl_px, "placed": placed}

    def cancel_all(self, symbol: str) -> Any:
        return self._http("DELETE", self.v["allOpen"], {"symbol": symbol}, signed=True, weight=1, is_order=True)

    def _fill_ledger(self, symbol: str, order_id: Any, start_ms: int = 0) -> Dict[str, Any]:
        params = {"symbol": symbol, "limit": 1000}
        if start_ms > 0: params["startTime"] = int(start_ms)
        rows = self._http("GET", self.v["trades"], params, signed=True, weight=5)
        matched = [x for x in rows if str(x.get("orderId")) == str(order_id)]
        if not matched:
            raise RuntimeError("order fill ledger unavailable for order %s" % order_id)
        qty = sum(finite(x.get("qty")) for x in matched)
        if qty <= 0:
            raise RuntimeError("zero filled quantity for order %s" % order_id)
        avg = sum(finite(x.get("price")) * finite(x.get("qty")) for x in matched) / qty
        commission = sum(finite(x.get("commission")) for x in matched)
        realized = sum(finite(x.get("realizedPnl")) for x in matched)
        return {"avg": avg, "qty": qty, "commission": commission, "rp": realized,
                "order_id": order_id, "fill_source": "userTrades"}

    def resolve_fill(self, symbol: str, order_id: Any, fallback_avg: Optional[float] = None,
                     qty: Optional[float] = None, start_ms: int = 0) -> Dict[str, Any]:
        time.sleep(0.15)
        try:
            return self._fill_ledger(symbol, order_id, start_ms)
        except Exception as exc:
            self.log("fill reconciliation failed %s: %s" % (symbol, exc))
            return {"avg": fallback_avg, "qty": qty, "commission": None, "rp": None,
                    "order_id": order_id, "fill_source": "orderAck_unreconciled"}

    def open_market(self, symbol: str, side: str, risk_or_notional: float, leverage: int,
                    tp_pct: float, sl_pct: float, max_notional: Optional[float] = None) -> Dict[str, Any]:
        symbol = symbol.upper(); side = side.upper()
        if side not in ("LONG", "SHORT"): raise ValueError("side must be LONG/SHORT")
        balance = self.balance_usdt()
        bid, ask, entry = self.book(symbol)
        lev = self.set_leverage(symbol, int(leverage))
        self.set_margin(symbol, True)
        if max_notional is not None:
            cap = finite(max_notional)
            if risk_or_notional <= 1.0:
                requested = min(cap, balance * max(0.0, risk_or_notional) * lev)
            else:
                requested = min(cap, risk_or_notional)
        else:
            requested = balance * max(0.0, risk_or_notional) * lev if risk_or_notional <= 1.0 else risk_or_notional
        if requested <= 0:
            raise RuntimeError("zero executable notional")
        qty = self._order_qty(symbol, requested, entry)
        dual = self.position_mode()
        pos_side = side if dual else "BOTH"
        self.flock.acquire(timeout=8.0, blocking=True)
        try:
            ack = self.place_market(symbol, "BUY" if side == "LONG" else "SELL", qty,
                                    position_side=pos_side if dual else None)
        finally:
            self.flock.release()
        oid = ack.get("orderId")
        fill = self.resolve_fill(symbol, oid, entry, qty, int(time.time() * 1000) - 5000)
        if fill["avg"] is None or fill["commission"] is None or fill["rp"] is None:
            raise RuntimeError("market order accepted but fill ledger is not reconciled")
        actual_qty = float(fill["qty"])
        avg = float(fill["avg"])
        tp = avg * (1.0 + float(tp_pct) / 100.0) if side == "LONG" else avg * (1.0 - float(tp_pct) / 100.0)
        sl = avg * (1.0 - float(sl_pct) / 100.0) if side == "LONG" else avg * (1.0 + float(sl_pct) / 100.0)
        protect = self.place_protect(symbol, side, avg, tp, sl, pos_side if dual else None)
        return {"symbol": symbol, "side": side, "entry": avg, "qty": actual_qty,
                "tp": protect["tp"], "sl": protect["sl"], "commission": fill["commission"],
                "realized_pnl": fill["rp"], "fill_source": fill["fill_source"],
                "oid": oid, "leverage": lev, "pos_side": pos_side}

    def close_market(self, symbol: str, side: str, qty: float,
                     position_side: Optional[str] = None) -> Dict[str, Any]:
        dual = self.position_mode()
        ps = position_side if position_side in ("LONG", "SHORT") else (side if dual else "BOTH")
        close_side = "SELL" if side.upper() == "LONG" else "BUY"
        self.flock.acquire(timeout=8.0, blocking=True)
        try:
            ack = self.place_market(symbol, close_side, qty, position_side=ps if dual else None, reduce_only=not dual)
        finally:
            self.flock.release()
        oid = ack.get("orderId")
        return self.resolve_fill(symbol, oid, None, qty, int(time.time() * 1000) - 5000)

    def funding_veto(self, symbol: str, side: str, max_rate: Optional[float] = None) -> Optional[str]:
        d = self._http("GET", self.v["premium"], {"symbol": symbol}, signed=False, weight=1)
        rate = finite(d.get("lastFundingRate"))
        lim = float(max_rate if max_rate is not None else self.env.get("MAX_FUNDING_RATE", "0.0025"))
        adverse = rate if side.upper() == "LONG" else -rate
        return "adverse funding %.8f > %.8f" % (adverse, lim) if adverse > lim else None

class CircuitBreaker:
    def __init__(self, fail_threshold: int = 4, cooldown_sec: float = 180):
        self.threshold, self.cooldown = max(1, fail_threshold), max(1.0, cooldown_sec)
        self.failures, self.blocked_until = 0, 0.0
        self.lock = threading.Lock()

    def allow(self) -> bool:
        with self.lock: return time.time() >= self.blocked_until

    def record_failure(self) -> None:
        with self.lock:
            self.failures += 1
            if self.failures >= self.threshold:
                self.blocked_until = time.time() + self.cooldown
                self.failures = 0

    def record_success(self) -> None:
        with self.lock: self.failures = 0

class DynamicTrailingStopEngine:
    def __init__(self, kernel: LiveKernel, log_fn=None):
        self.kernel, self.log = kernel, log_fn or (lambda m: None)
        self.positions: Dict[str, Dict[str, Any]] = {}

    def register(self, symbol, side, entry, tp, sl, position_side=None):
        self.positions[symbol] = {"side":side,"entry":entry,"tp":tp,"sl":sl,"position_side":position_side,"peak":entry,"stage":0}

    def update(self, symbol: str, mark: float) -> Optional[float]:
        p = self.positions.get(symbol)
        if not p or mark <= 0: return None
        side = p["side"].upper()
        p["peak"] = max(p["peak"], mark) if side == "LONG" else min(p["peak"], mark)
        entry = p["entry"]
        dist = abs(p["tp"] - entry)
        gain = (mark-entry) if side=="LONG" else (entry-mark)
        if dist <= 0 or gain <= 0: return None
        stage = 2 if gain >= dist*0.75 else 1 if gain >= dist*0.40 else 0
        if stage <= p["stage"]: return None
        p["stage"] = stage
        lock_dist = dist*(0.20 if stage == 1 else 0.55)
        new_sl = entry + lock_dist if side=="LONG" else entry - lock_dist
        try:
            self.kernel.cancel_all(symbol)
            self.kernel.place_protect(symbol, side, entry, p["tp"], new_sl, p.get("position_side"))
            p["sl"] = new_sl
            self.log("TRAIL %s stage=%s stop=%s" % (symbol, stage, new_sl))
            return new_sl
        except Exception as exc:
            self.log("TRAIL failure %s: %s" % (symbol, exc))
            raise

    def forget(self, symbol): self.positions.pop(symbol, None)

class PartialProfitEngine:
    def __init__(self, kernel: LiveKernel, log_fn=None):
        self.kernel, self.log = kernel, log_fn or (lambda m: None)
        self.positions = {}

    def register(self, symbol, side, entry, tp, sl, qty, position_side=None):
        self.positions[symbol] = {"side":side,"entry":entry,"tp":tp,"sl":sl,"qty":qty,"position_side":position_side}

    def update(self, symbol, mark):
        return None

    def forget(self, symbol): self.positions.pop(symbol, None)

class CryptographicAuditLedger:
    def __init__(self, path: str):
        self.path = path
        self.lock = threading.Lock()
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

    def append(self, event: Dict[str, Any]) -> None:
        clean = dict(event)
        clean.pop("secret", None); clean.pop("api_secret", None); clean.pop("api_key", None)
        raw = json.dumps(clean, sort_keys=True, separators=(",", ":"), default=str)
        with self.lock:
            prev = ""
            if os.path.exists(self.path):
                try:
                    with open(self.path, "rb") as fh:
                        for line in fh:
                            try: prev = json.loads(line.decode()).get("hash","")
                            except Exception: continue
                except Exception: pass
            digest = hashlib.sha256((prev + raw).encode()).hexdigest()
            record = {"ts": time.time(), "hash": digest, "prev_hash": prev, **clean}
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

def _ema(values: List[float], period: int) -> Optional[float]:
    if len(values) < period: return None
    a = 2.0 / (period + 1.0); out = sum(values[:period]) / period
    for x in values[period:]: out = a*x + (1-a)*out
    return out

def ema(values, period=14): return _ema([finite(x) for x in values], int(period))

def rsi(values, period=14):
    x=[finite(v) for v in values]
    if len(x)<period+1:return None
    gains=[];losses=[]
    for i in range(1,len(x)):
        d=x[i]-x[i-1];gains.append(max(d,0.0));losses.append(max(-d,0.0))
    ag=sum(gains[-period:])/period;al=sum(losses[-period:])/period
    if al==0:return 100.0
    return 100.0-(100.0/(1.0+ag/al))

def atr(highs, lows=None, closes=None, period=14):
    if closes is None:
        closes=[finite(x) for x in highs]
        if len(closes)<period+1:return None
        tr=[abs(closes[i]-closes[i-1]) for i in range(1,len(closes))]
    else:
        h=[finite(x) for x in highs];l=[finite(x) for x in lows];c=[finite(x) for x in closes]
        if len(c)<period+1:return None
        tr=[max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1])) for i in range(1,len(c))]
    return sum(tr[-period:])/period
