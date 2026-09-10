#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Honeycomb cross-process Binance REST guard + WS-first market cache.

Additive safety layer: it does not replace any existing engine. It provides
one IP-wide rate gate, persistent ban backoff, and an authenticated-independent
public market cache fed by Binance Futures WebSocket streams.
"""
from __future__ import annotations

import fcntl
import io
import json
import os
import re
import sqlite3
import threading
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional

ROOT = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.join(ROOT, ".honeycomb_runtime")
os.makedirs(RUNTIME, exist_ok=True)
STATE_PATH = os.path.join(RUNTIME, "binance_guard.json")
LOCK_PATH = os.path.join(RUNTIME, "binance_guard.lock")
WS_LOCK_PATH = os.path.join(RUNTIME, "binance_market_ws.lock")
CACHE_DB = os.path.join(RUNTIME, "market_cache.db")

SAFE_WEIGHT_PER_MIN = float(os.getenv("BINANCE_SAFE_WEIGHT_PER_MIN", "900"))
SAFE_ORDERS_PER_10S = float(os.getenv("BINANCE_SAFE_ORDERS_PER_10S", "60"))
PUBLIC_CACHE_TTL = float(os.getenv("BINANCE_PUBLIC_CACHE_TTL", "8"))
EXCHANGEINFO_TTL = float(os.getenv("BINANCE_EXCHANGEINFO_TTL", "21600"))
WS_ENABLED = os.getenv("BINANCE_WS_FIRST", "1") != "0"

_BINANCE_HOSTS = {
    "fapi.binance.com", "dapi.binance.com",
    "testnet.binancefuture.com", "demo-fapi.binance.com",
}


def _load_env_file() -> Dict[str, str]:
    out: Dict[str, str] = {}
    p = os.path.join(ROOT, ".env")
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        out[k.strip()] = v.strip().split("#")[0].strip()
        except Exception:
            pass
    for k, v in os.environ.items():
        out.setdefault(k, v)
    return out


ENV = _load_env_file()


def parse_retry_after(headers: Any) -> Optional[float]:
    try:
        value = headers.get("Retry-After") if headers is not None else None
        if value is None:
            return None
        return max(0.0, float(value))
    except Exception:
        return None


def parse_ban_until(body: str) -> Optional[float]:
    if not body:
        return None
    m = re.search(r"banned\s+until\s+(\d{10,16})", body, re.I)
    if not m:
        return None
    try:
        ms = int(m.group(1))
        return ms / 1000.0 if ms > 10_000_000_000 else float(ms)
    except Exception:
        return None


def _load_state() -> Dict[str, Any]:
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _write_state(d: Dict[str, Any]) -> None:
    tmp = STATE_PATH + ".tmp.%d" % os.getpid()
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, sort_keys=True)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, STATE_PATH)


class _FileGuard:
    def __enter__(self):
        self.fd = open(LOCK_PATH, "a+")
        fcntl.flock(self.fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, *_):
        try:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
        finally:
            self.fd.close()


def _weight_for_url(url: str, method: str) -> int:
    p = urllib.parse.urlparse(url).path
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    if p.endswith("/klines"):
        limit = int(q.get("limit", [500])[0])
        return 1 if limit < 100 else (2 if limit < 500 else 5 if limit <= 1000 else 10)
    if p.endswith("/exchangeInfo"):
        return 1
    if p.endswith("/ticker/bookTicker"):
        return 2 if q.get("symbol") else 5
    if p.endswith("/ticker/price") or p.endswith("/premiumIndex") or p.endswith("/time"):
        return 1
    if p.endswith("/balance") or p.endswith("/account") or p.endswith("/positionRisk"):
        return 5
    if p.endswith("/userTrades"):
        return 5
    return 1


def _is_order_path(url: str) -> bool:
    p = urllib.parse.urlparse(url).path
    return p.endswith("/order") or p.endswith("/allOpenOrders") or p.endswith("/leverage") or p.endswith("/marginType")


class BinanceRateGate:
    def acquire(self, weight: int, order: bool = False) -> None:
        weight = max(1, int(weight))
        while True:
            with _FileGuard():
                now = time.time()
                st = _load_state()
                ban_until = float(st.get("ban_until", 0.0) or 0.0)
                if ban_until > now:
                    raise RuntimeError("BINANCE_GUARD_BAN %.1fs remaining" % (ban_until - now))
                ws = float(st.get("weight_window_start", now))
                used = float(st.get("weight_used", 0.0))
                if now - ws >= 60.0:
                    ws, used = now, 0.0
                os_ = float(st.get("order_window_start", now))
                orders = float(st.get("orders_used", 0.0))
                if now - os_ >= 10.0:
                    os_, orders = now, 0.0
                wait_w = max(0.0, 60.0 - (now - ws)) if used + weight > SAFE_WEIGHT_PER_MIN else 0.0
                wait_o = max(0.0, 10.0 - (now - os_)) if order and orders + 1 > SAFE_ORDERS_PER_10S else 0.0
                wait = max(wait_w, wait_o)
                if wait <= 0:
                    st.update({"weight_window_start": ws, "weight_used": used + weight,
                               "order_window_start": os_, "orders_used": orders + (1 if order else 0),
                               "last_acquire": now})
                    _write_state(st)
                    return
            time.sleep(max(0.05, wait))

    def record_http_error(self, status: int, body: str, headers: Any) -> None:
        now = time.time()
        retry = parse_retry_after(headers)
        ban = parse_ban_until(body)
        if status == 418 or "-1003" in (body or ""):
            until = ban or (now + max(retry or 60.0, 60.0))
        elif status == 429:
            until = now + max(retry or 2.0, 2.0)
        else:
            return
        with _FileGuard():
            st = _load_state()
            st["ban_until"] = max(float(st.get("ban_until", 0.0) or 0.0), until)
            st["last_rate_error"] = {"status": status, "until": until, "ts": now}
            _write_state(st)


RATE_GATE = BinanceRateGate()


class _SimpleResponse:
    def __init__(self, payload: bytes, url: str, status: int = 200):
        self._bio = io.BytesIO(payload)
        self.url = url
        self.status = status
        self.code = status
        self.headers = {"Content-Type": "application/json", "X-Honeycomb-Source": "binance-ws-cache"}

    def read(self, amt: int = -1) -> bytes:
        return self._bio.read(amt)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        self._bio.close()


_db_lock = threading.RLock()


def _db() -> sqlite3.Connection:
    os.makedirs(RUNTIME, exist_ok=True)
    con = sqlite3.connect(CACHE_DB, timeout=10)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, ts REAL, payload TEXT NOT NULL)")
    con.execute("CREATE TABLE IF NOT EXISTS book(symbol TEXT PRIMARY KEY, ts REAL, bid TEXT, ask TEXT, bid_qty TEXT, ask_qty TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS mark(symbol TEXT PRIMARY KEY, ts REAL, payload TEXT NOT NULL)")
    con.execute("CREATE TABLE IF NOT EXISTS kline(symbol TEXT, interval TEXT, open_time INTEGER, payload TEXT NOT NULL, PRIMARY KEY(symbol,interval,open_time))")
    con.execute("CREATE INDEX IF NOT EXISTS idx_kline ON kline(symbol,interval,open_time)")
    con.commit()
    return con


def _put_kv(k: str, payload: Any) -> None:
    with _db_lock:
        con = _db()
        con.execute("INSERT OR REPLACE INTO kv(k,ts,payload) VALUES(?,?,?)", (k, time.time(), json.dumps(payload, separators=(",", ":"))))
        con.commit(); con.close()


def _get_kv(k: str, ttl: float) -> Optional[Any]:
    with _db_lock:
        con = _db(); row = con.execute("SELECT ts,payload FROM kv WHERE k=?", (k,)).fetchone(); con.close()
    if not row or time.time() - float(row[0]) > ttl:
        return None
    try:
        return json.loads(row[1])
    except Exception:
        return None


def _put_book(data: Dict[str, Any]) -> None:
    try:
        s = str(data.get("s") or data.get("symbol")).upper()
        if not s: return
        with _db_lock:
            con = _db()
            con.execute("INSERT OR REPLACE INTO book(symbol,ts,bid,ask,bid_qty,ask_qty) VALUES(?,?,?,?,?,?)",
                        (s, time.time(), str(data.get("b") or data.get("bidPrice") or 0), str(data.get("a") or data.get("askPrice") or 0),
                         str(data.get("B") or data.get("bidQty") or 0), str(data.get("A") or data.get("askQty") or 0)))
            con.commit(); con.close()
    except Exception:
        pass


def _put_mark(data: Dict[str, Any]) -> None:
    try:
        s = str(data.get("s") or data.get("symbol")).upper()
        if not s: return
        with _db_lock:
            con = _db(); con.execute("INSERT OR REPLACE INTO mark(symbol,ts,payload) VALUES(?,?,?)", (s,time.time(),json.dumps(data,separators=(",",":")))); con.commit(); con.close()
    except Exception:
        pass


def _put_kline(symbol: str, interval: str, k: Dict[str, Any]) -> None:
    try:
        row = [int(k["t"]), k["o"], k["h"], k["l"], k["c"], k["v"], int(k.get("T",0)), k.get("q","0"), int(k.get("n",0)), k.get("V","0"), k.get("Q","0"), "0"]
        with _db_lock:
            con = _db()
            con.execute("INSERT OR REPLACE INTO kline(symbol,interval,open_time,payload) VALUES(?,?,?,?)", (symbol.upper(), interval, row[0], json.dumps(row,separators=(",",":"))))
            con.execute("DELETE FROM kline WHERE symbol=? AND interval=? AND open_time NOT IN (SELECT open_time FROM kline WHERE symbol=? AND interval=? ORDER BY open_time DESC LIMIT 160)", (symbol.upper(), interval, symbol.upper(), interval))
            con.commit(); con.close()
    except Exception:
        pass


def _get_book(symbol: str) -> Optional[Dict[str, Any]]:
    with _db_lock:
        con = _db(); row = con.execute("SELECT ts,bid,ask,bid_qty,ask_qty FROM book WHERE symbol=?", (symbol.upper(),)).fetchone(); con.close()
    if not row or time.time()-row[0] > PUBLIC_CACHE_TTL: return None
    return {"symbol":symbol.upper(),"bidPrice":row[1],"askPrice":row[2],"bidQty":row[3],"askQty":row[4]}


def _get_mark(symbol: str) -> Optional[Dict[str, Any]]:
    with _db_lock:
        con = _db(); row = con.execute("SELECT ts,payload FROM mark WHERE symbol=?", (symbol.upper(),)).fetchone(); con.close()
    if not row or time.time()-row[0] > PUBLIC_CACHE_TTL: return None
    try: return json.loads(row[1])
    except Exception: return None


def _get_klines(symbol: str, interval: str, limit: int) -> Optional[list]:
    with _db_lock:
        con = _db(); rows = con.execute("SELECT payload FROM kline WHERE symbol=? AND interval=? ORDER BY open_time DESC LIMIT ?", (symbol.upper(), interval, int(limit))).fetchall(); con.close()
    if len(rows) < int(limit): return None
    return [json.loads(r[0]) for r in reversed(rows)]


def cache_public(url: str) -> Optional[Any]:
    u = urllib.parse.urlparse(url)
    if u.hostname not in _BINANCE_HOSTS: return None
    q = urllib.parse.parse_qs(u.query); p = u.path; symbol = (q.get("symbol") or [""])[0].upper()
    if p.endswith("/exchangeInfo"): return _get_kv("exchangeInfo:" + u.hostname, EXCHANGEINFO_TTL)
    if p.endswith("/ticker/bookTicker") and symbol: return _get_book(symbol)
    if p.endswith("/premiumIndex") and symbol: return _get_mark(symbol)
    if p.endswith("/ticker/price") and symbol:
        b = _get_book(symbol)
        if b:
            bid, ask = float(b["bidPrice"]), float(b["askPrice"])
            return {"symbol": symbol, "price": "%.12f" % ((bid + ask) / 2.0)}
    if p.endswith("/klines") and symbol:
        interval = (q.get("interval") or ["1m"])[0]; limit = int((q.get("limit") or [500])[0])
        return _get_klines(symbol, interval, limit)
    return None


def cache_seed_public(url: str, payload: Any) -> None:
    u = urllib.parse.urlparse(url); p = u.path; q = urllib.parse.parse_qs(u.query); symbol = (q.get("symbol") or [""])[0].upper()
    try:
        if p.endswith("/exchangeInfo"):
            _put_kv("exchangeInfo:" + u.hostname, payload); return
        if p.endswith("/ticker/bookTicker") and isinstance(payload, dict): _put_book(payload); return
        if p.endswith("/premiumIndex") and isinstance(payload, dict): _put_mark(payload); return
        if p.endswith("/klines") and symbol and isinstance(payload, list):
            interval = (q.get("interval") or ["1m"])[0]
            for row in payload:
                _put_kline(symbol, interval, {"t":row[0],"T":row[6],"o":row[1],"h":row[2],"l":row[3],"c":row[4],"v":row[5],"q":row[7],"n":row[8],"V":row[9],"Q":row[10]})
    except Exception:
        pass


_ws_started = False
_ws_guard = threading.Lock()


def _symbols() -> list[str]:
    raw = ENV.get("LIVE_SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,ADAUSDT,DOGEUSDT,AVAXUSDT,LINKUSDT,LTCUSDT")
    return [x.strip().upper() for x in raw.split(",") if x.strip()]


def _ws_url() -> str:
    venue = (ENV.get("FUTURES_MARKET") or ENV.get("VENUE") or "USDT_M").upper()
    base = "wss://dstream.binance.com/stream?streams=" if "COIN" in venue else "wss://fstream.binance.com/stream?streams="
    streams=[]
    for s in _symbols():
        x=s.lower(); streams += [x+"@bookTicker", x+"@markPrice@1s"]
        for tf in ("1m","3m","5m","15m","30m","1h","2h","4h"): streams.append(x+"@kline_"+tf)
    return base + "/".join(streams)


def _ws_worker() -> None:
    try: import websocket
    except Exception: return
    if not WS_ENABLED: return
    fd = open(WS_LOCK_PATH, "a+")
    try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError: fd.close(); return
    try:
        while True:
            ws = None
            try:
                ws = websocket.create_connection(_ws_url(), timeout=20, enable_multithread=True)
                while True:
                    raw = ws.recv()
                    if not raw: raise RuntimeError("ws closed")
                    obj=json.loads(raw); d=obj.get("data", obj); e=d.get("e")
                    if e == "bookTicker": _put_book(d)
                    elif e in ("markPriceUpdate", "markPrice"): _put_mark(d)
                    elif e == "kline":
                        k=d.get("k") or {}; _put_kline(str(d.get("s") or k.get("s") or ""), str(k.get("i") or ""), k)
            except Exception:
                try:
                    if ws: ws.close()
                except Exception: pass
                time.sleep(3)
    finally:
        try: fcntl.flock(fd, fcntl.LOCK_UN)
        except Exception: pass
        fd.close()


def start_ws() -> None:
    global _ws_started
    with _ws_guard:
        if _ws_started: return
        _ws_started=True
        threading.Thread(target=_ws_worker, name="honeycomb-binance-ws", daemon=True).start()


_ORIGINAL_URLOPEN = urllib.request.urlopen
_PATCHED = False


def guarded_urlopen(url_or_req: Any, data=None, timeout=None, *args, **kwargs):
    req_url = url_or_req.full_url if hasattr(url_or_req, "full_url") else str(url_or_req)
    host = urllib.parse.urlparse(req_url).hostname
    if host not in _BINANCE_HOSTS:
        return _ORIGINAL_URLOPEN(url_or_req, data=data, timeout=timeout, *args, **kwargs)
    method = getattr(url_or_req, "method", None) or ("POST" if data is not None else "GET")
    cached = cache_public(req_url) if method == "GET" else None
    if cached is not None:
        return _SimpleResponse(json.dumps(cached,separators=(",",":" )).encode(), req_url)
    RATE_GATE.acquire(_weight_for_url(req_url, method), _is_order_path(req_url))
    try:
        resp = _ORIGINAL_URLOPEN(url_or_req, data=data, timeout=timeout, *args, **kwargs)
        if method == "GET":
            raw = resp.read()
            try: payload=json.loads(raw.decode("utf-8"))
            except Exception: payload=None
            if payload is not None: cache_seed_public(req_url, payload)
            return _SimpleResponse(raw, req_url, getattr(resp,"status",200))
        return resp
    except Exception as e:
        code=getattr(e,"code",None); body=""
        try: body=e.read().decode("utf-8") if hasattr(e,"read") else str(e)
        except Exception: body=str(e)
        if code in (418,429) or "-1003" in body:
            RATE_GATE.record_http_error(int(code or 418), body, getattr(e,"headers",None))
        raise


def install() -> None:
    global _PATCHED
    if _PATCHED: return
    _PATCHED=True
    lp = os.environ.get("LEARNING_DB_PATH") or ENV.get("LEARNING_DB_PATH") or ""
    if "," in lp:
        first = lp.split(",",1)[0].strip()
        if first: os.environ["LEARNING_DB_PATH"] = first
    urllib.request.urlopen = guarded_urlopen
    start_ws()

install()
