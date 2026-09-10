#!/data/data/com.termux/files/usr/bin/python3
# -*- coding: utf-8 -*-
"""
α-HONEYCOMB LiveKernel — HARDENED SIGNATURE MODULE (Termux-safe)
===============================================================
- Sadece / eğik çizgi kullanılır
- Asla \\ veya karışık ayırıcı yok
- Tüm yollar os.path / pathlib ile üretilir
- $HOME ve $TMPDIR kullanılır
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

def hardened_sign(secret: bytes, params: Dict[str, Any]) -> str:
    """
    Binance Futures resmi imza kuralı (sıralı + None-free).
    Akademik ispat:
    1. clean = {k: str(v) for k,v in params.items() if v is not None}
    2. qs = urlencode(sorted(clean.items()))
    3. sig = HMAC_SHA256(secret, qs.encode('utf-8')).hexdigest()
    """
    if not secret:
        raise RuntimeError("SECRET EMPTY — imza üretilemez. BINANCE_SECRET_KEY kontrol et.")
    clean = {str(k): str(v) for k, v in params.items() if v is not None}
    qs = urllib.parse.urlencode(sorted(clean.items()), doseq=True)
    sig = hmac.new(secret, qs.encode("utf-8"), hashlib.sha256).hexdigest()
    return qs + "&signature=" + sig


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
    """Fail-closed, time-sync, -2015 hard-stop, sorted-sign HTTP katmanı."""
    if time.time() < getattr(self, "_stale_until", 0.0):
        raise RuntimeError("stale-halt active %.0fs" % (self._stale_until - time.time()))

    if hasattr(self, "bucket"):
        self.bucket.take(weight, is_order)

    params = dict(params or {})
    if signed:
        if not self.secret:
            raise RuntimeError("API SECRET boş — signed istek atılamaz")
        params["timestamp"] = int(time.time() * 1000) + getattr(self, "_off", 0)
        params["recvWindow"] = getattr(self, "recv", 10000)
        body = hardened_sign(self.secret, params)
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

    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
            with urllib.request.urlopen(req, timeout=12) as resp:
                raw = resp.read().decode()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            raw = e.read().decode() if e.fp else str(e)
            try:
                err = json.loads(raw)
            except Exception:
                err = {"msg": raw}
            code = err.get("code")
            if code in (-1021, -1022):
                if hasattr(self, "sync_time"):
                    self.sync_time()
                last_err = RuntimeError("time/sig %s" % err)
                time.sleep(0.15 * (attempt + 1))
                if signed:
                    params["timestamp"] = int(time.time() * 1000) + getattr(self, "_off", 0)
                    body = hardened_sign(self.secret, params)
                    url = self.v["rest"] + path + (("?" + body) if method.upper() == "GET" and body else "")
                    data = body.encode("utf-8") if method.upper() != "GET" else None
                continue
            if code == -2015:
                raise RuntimeError(
                    "BINANCE -2015: Invalid API-key, IP or permissions. "
                    "LIVE_ARMED kapatıldı. Key/IP whitelist kontrol et."
                )
            raise RuntimeError("HTTP %s: %s" % (e.code, err))
        except (urllib.error.URLError, ConnectionResetError, TimeoutError, OSError) as e:
            last_err = e
            self._stale_until = time.time() + min(30, 2 ** attempt + 1)
            time.sleep(0.3 * (attempt + 1))
    raise RuntimeError("net fail after %d retries: %s" % (retries, last_err))


def apply_hardened_sign(kernel_instance):
    """Mevcut LiveKernel instance'ına hardened imza uygular."""
    kernel_instance._sign = lambda params: hardened_sign(kernel_instance.secret, params)
    kernel_instance._http = lambda *a, **kw: hardened_http(kernel_instance, *a, **kw)
    return kernel_instance
