#!/data/data/com.termux/files/usr/bin/python3
# -*- coding: utf-8 -*-
"""
net_shield.py — LIVE network resilience for Binance fapi/dapi on Termux.

What it fixes in ALPHA 104 storm:
  - Consecutive Connection reset (104) was treated as try next symbol
  - No global cool-down when the path is dead
  - No jittered exponential backoff

No invented fills. No price if the book cannot be read.
"""
from __future__ import annotations

import json
import random
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

_lock = threading.RLock()
_state = {
    "fails": 0,
    "locked_until": 0.0,
    "last_ok": 0.0,
    "last_err": "",
}

_DEFAULT_TIMEOUT = 8
_MAX_BACKOFF = 45.0
_TRIP_AFTER = 3
_COOLDOWN_BASE = 8.0

_OP = urllib.request.build_opener()


def breaker_ok() -> bool:
    with _lock:
        return time.time() >= _state["locked_until"]


def breaker_status() -> Dict[str, Any]:
    with _lock:
        rem = max(0.0, _state["locked_until"] - time.time())
        return {
            "ok": rem <= 0,
            "fails": _state["fails"],
            "cooldown_remaining_sec": round(rem, 1),
            "last_err": _state["last_err"],
            "last_ok_age_sec": round(time.time() - _state["last_ok"], 1) if _state["last_ok"] else None,
        }


def _trip(err: str) -> None:
    with _lock:
        _state["fails"] += 1
        _state["last_err"] = str(err)[:200]
        if _state["fails"] >= _TRIP_AFTER:
            exp = min(_MAX_BACKOFF, _COOLDOWN_BASE * (2 ** min(_state["fails"] - _TRIP_AFTER, 4)))
            exp += random.uniform(0.0, 1.5)
            _state["locked_until"] = time.time() + exp


def _ok() -> None:
    with _lock:
        _state["fails"] = 0
        _state["locked_until"] = 0.0
        _state["last_ok"] = time.time()
        _state["last_err"] = ""


def http_get_json(url: str, timeout: float = _DEFAULT_TIMEOUT, retries: int = 3) -> Any:
    if not breaker_ok():
        st = breaker_status()
        raise RuntimeError("NET_BREAKER cool=%.1fs last=%s" % (st["cooldown_remaining_sec"], st["last_err"]))
    last: Optional[Exception] = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "honeycomb-net-shield/1", "Accept": "application/json"},
                method="GET",
            )
            with _OP.open(req, timeout=timeout) as r:
                body = r.read().decode("utf-8")
            _ok()
            return json.loads(body) if body else {}
        except Exception as e:
            last = e
            msg = str(e)
            if any(x in msg for x in ("104", "Connection reset", "timed out", "Network is unreachable", "Temporary failure")):
                _trip(msg)
                time.sleep(min(2.0, 0.25 * (2 ** attempt)) + random.uniform(0, 0.2))
                if not breaker_ok():
                    break
                continue
            if isinstance(e, urllib.error.HTTPError) and e.code in (418, 429):
                _trip("HTTP %d" % e.code)
                time.sleep(5.0 + random.uniform(0, 2))
                break
            raise
    raise RuntimeError("GET_FAIL %s | %s" % (url[:80], last))


def klines(symbol: str, interval: str = "1m", limit: int = 60, base: str = "https://fapi.binance.com") -> Tuple[List[float], List[float]]:
    url = "%s/fapi/v1/klines?symbol=%s&interval=%s&limit=%d" % (base.rstrip("/"), symbol, interval, limit)
    data = http_get_json(url)
    closes = [float(x[4]) for x in data]
    volumes = [float(x[5]) for x in data]
    return closes, volumes


def book_ticker(symbol: str, base: str = "https://fapi.binance.com") -> Dict[str, float]:
    url = "%s/fapi/v1/ticker/bookTicker?symbol=%s" % (base.rstrip("/"), symbol)
    data = http_get_json(url)
    bid = float(data.get("bidPrice") or 0)
    ask = float(data.get("askPrice") or 0)
    if bid <= 0 or ask <= 0 or ask < bid:
        raise RuntimeError("bad_book %s" % symbol)
    return {"bid": bid, "ask": ask, "mid": (bid + ask) / 2.0}


def server_time(base: str = "https://fapi.binance.com") -> int:
    data = http_get_json("%s/fapi/v1/time" % base.rstrip("/"))
    return int(data["serverTime"])


def scan_or_skip(symbols: List[str], fetch_one, log_fn=None) -> None:
    log = log_fn or (lambda m: None)
    if not breaker_ok():
        st = breaker_status()
        log("NET_HALT %.1fs (fails=%d) — sembol taramasi durdu" % (st["cooldown_remaining_sec"], st["fails"]))
        time.sleep(min(5.0, max(1.0, st["cooldown_remaining_sec"])))
        return
    for sym in symbols:
        if not breaker_ok():
            st = breaker_status()
            log("NET_HALT mid-scan %.1fs — kalan semboller atlandi" % st["cooldown_remaining_sec"])
            return
        try:
            fetch_one(sym)
        except Exception as e:
            log("scan %s: %s" % (sym, e))
            if not breaker_ok():
                return
