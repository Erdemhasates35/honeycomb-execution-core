#!/data/data/com.termux/files/usr/bin/python3
# -*- coding: utf-8 -*-
"""alpha-HONEYCOMB LiveKernel - HARDENED SIGNATURE v2 (Termux-safe)

v2 degisiklikleri:
- Binance hata govdesi her zaman cozulur; bos msg asla sessiz gecilmez.
- -4056 (margin type zaten ayarli) IDEMPOTENT basari sayilir -> 400 spam'i biter.
- -1021/-1022 disinda retry YOK; 400 serisi aninda siniflanir.
- Devre kesici: ayni path'te 3 ardisik hata -> 60 sn, 10 hata -> 15 dk mola.
- Agirlik sayaci: dakikada 900 weight ustunde uyar, 1200'de zorunlu nefes.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional

RECV_WINDOW = 5000

CODE_MAP = {
    -1021: (True,  "timestamp ahead/behind -> sync_time"),
    -1022: (True,  "signature invalid -> sync & retry"),
    -1003: (True,  "too many requests -> breaker"),
    -4056: (False, "margin type already set -> IDEMPOTENT OK"),
    -4059: (False, "position side already set -> IDEMPOTENT OK"),
    -2015: (False, "HARD STOP: invalid API-key/IP/permissions"),
    -2014: (False, "HARD STOP: API-key format invalid"),
    -1111: (False, "precision hatasi: qty/fiyat adimini duzelt"),
    -1013: (False, "invalid qty: minQty/stepSize ihlali"),
    -2011: (False, "unknown order sent"),
    -4003: (False, "quantity less than zero"),
}


class BinanceError(RuntimeError):
    def __init__(self, code: int, msg: str, path: str = ""):
        self.code = code
        self.msg = msg
        self.path = path
        super().__init__(f"[BINANCE {code}] {msg or '(bos msg)'} @ {path}")


def hardened_sign(secret: bytes | str, params: Dict[str, Any]) -> str:
    if not secret:
        raise RuntimeError("SECRET EMPTY - imza uretilemez.")
    if isinstance(secret, str):
        secret = secret.encode("utf-8")
    clean = {str(k): str(v) for k, v in params.items() if v is not None}
    qs = urllib.parse.urlencode(sorted(clean.items()))
    return hmac.new(secret, qs.encode("utf-8"), hashlib.sha256).hexdigest()


def _breakers(self) -> dict:
    if not hasattr(self, "_brk"):
        self._brk = {}
    return self._brk


def _breaker_check(self, path: str) -> None:
    b = _breakers(self).get(path)
    if b and time.time() < b:
        wait = int(b - time.time())
        raise RuntimeError(f"DEVRE KESICI: {path} {wait} sn bekliyor (ust uste hata limiti)")


def _breaker_hit(self, path: str) -> None:
    brk = _breakers(self)
    n = brk.get(path + "_n", 0) + 1
    brk[path + "_n"] = n
    brk[path] = time.time() + (60 if n < 10 else 900)


def _breaker_ok(self, path: str) -> None:
    _breakers(self)[path + "_n"] = 0


def hardened_http(
    self,
    method: str,
    path: str,
    params: Optional[Dict[str, Any]] = None,
    signed: bool = False,
    weight: int = 1,
    is_order: bool = False,
    retries: int = 3,
) -> Any:
    _breaker_check(self, path)

    if time.time() < getattr(self, "_stale_until", 0.0):
        raise RuntimeError("stale-halt active %.0fs" % (self._stale_until - time.time()))

    if hasattr(self, "bucket"):
        self.bucket.take(weight, is_order)

    w = getattr(self, "_wmin", None)
    now = time.time()
    if w is None or now - w[0] > 60:
        self._wmin = (now, weight)
    else:
        self._wmin = (w[0], w[1] + weight)
        if self._wmin[1] > 900:
            print(f"[WEIGHT] dakikada {self._wmin[1]} weight - sinira yaklasiliyor", flush=True)
        if self._wmin[1] > 1200:
            time.sleep(5)

    params = dict(params or {})
    if signed:
        if not self.secret:
            raise RuntimeError("API SECRET bos - istek atilmaz")
        params["timestamp"] = int(time.time() * 1000) + getattr(self, "_off", 0)
        params["recvWindow"] = RECV_WINDOW
        body = hardened_sign(self.secret, params)
        params["signature"] = body
    else:
        body = urllib.parse.urlencode(
            {str(k): str(v) for k, v in params.items() if v is not None}, doseq=True
        )

    url = self.v["rest"] + path + (("?" + body) if method.upper() == "GET" and body else "")
    data = body.encode("utf-8") if method.upper() != "GET" else None
    headers = {
        "X-MBX-APIKEY": self.key,
        "Content-Type": "application/x-www-form-urlencoded",
    }

    last_err: Optional[Exception] = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
            with urllib.request.urlopen(req, timeout=12) as resp:
                raw = resp.read().decode()
            _breaker_ok(self, path)
            return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            raw = e.read().decode() if e.fp else ""
            try:
                err = json.loads(raw)
            except Exception:
                err = {"code": -1, "msg": raw[:200] or "HTTP %s bos govde" % e.code}
            code = err.get("code", -1)
            msg = err.get("msg", "")
            if code in (-1021, -1022):
                if hasattr(self, "sync_time"):
                    self.sync_time()
                self._off = getattr(self, "_off", 0)
                params["timestamp"] = int(time.time() * 1000) + self._off
                if signed:
                    params["signature"] = hardened_sign(self.secret, params)
                    body2 = urllib.parse.urlencode(params)
                    url = self.v["rest"] + path + (("?" + body2) if method.upper() == "GET" else "")
                    data = body2.encode("utf-8") if method.upper() != "GET" else None
                time.sleep(0.15 * (attempt + 1))
                continue
            if code == -1003:
                _breaker_hit(self, path)
                ra = e.headers.get("Retry-After") if e.headers else None
                time.sleep(float(ra) if ra else 5)
                continue
            if code == -4056 or code == -4059:
                _breaker_ok(self, path)
                return {"ok": True, "idempotent": True, "code": code}
            if code == -2015:
                if hasattr(self, "disarm"):
                    self.disarm("BINANCE -2015: API-key/IP/permissions. LIVE_ARMED kapatildi.")
                raise RuntimeError("BINANCE -2015: Invalid API-key / IP / permissions. LIVE_ARMED kapat.")
            if code == -2014:
                if hasattr(self, "disarm"):
                    self.disarm("BINANCE -2014: API-key format. LIVE_ARMED kapatildi.")
                raise RuntimeError("BINANCE -2014: API-key format hatali. LIVE_ARMED kapat.")
            _breaker_hit(self, path)
            raise BinanceError(code, str(msg), path)
        except Exception as e:
            last_err = e
            self._stale_until = time.time() + min(30, 2 ** attempt + 1)
            time.sleep(0.3 * (attempt + 1))
    raise RuntimeError("net fail after retries: %s" % last_err)


def apply_hardened_sign(kernel_instance):
    kernel_instance._sign = lambda params: hardened_sign(kernel_instance.secret, params)
    kernel_instance._http = lambda *a, **kw: hardened_http(kernel_instance, *a, **kw)
    return kernel_instance
