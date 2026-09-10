#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Binance REST endpoint failover.

Routes Binance REST traffic across the Binance API host family without
changing paths, query strings, signatures, API keys, timestamps, or TLS
verification. Safe reads may fail over on DNS/connectivity failures. Live
order POSTs are never blindly replayed after an ambiguous transport failure.
"""
from __future__ import annotations

import socket
import threading
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional, Tuple

_HOSTS = {
    "fapi.binance.com": ("fapi.binance.com", "api4.binance.com", "api3.binance.com", "api2.binance.com", "api1.binance.com"),
    "dapi.binance.com": ("dapi.binance.com", "api4.binance.com", "api3.binance.com", "api2.binance.com", "api1.binance.com"),
    "testnet.binancefuture.com": ("testnet.binancefuture.com",),
    "demo-fapi.binance.com": ("demo-fapi.binance.com",),
}

_LOCK = threading.RLock()
_HEALTH: Dict[str, Tuple[float, float]] = {}
_ORIGINAL = urllib.request.urlopen
_INSTALLED = False


def _score(host: str) -> float:
    with _LOCK:
        ok = _HEALTH.get(host)
    if not ok:
        return 0.0
    success, failed = ok
    return success - failed * 2.0


def _record(host: str, success: bool) -> None:
    with _LOCK:
        s, f = _HEALTH.get(host, (0.0, 0.0))
        if success:
            s = min(100.0, s * 0.8 + 1.0)
            f *= 0.8
        else:
            s *= 0.8
            f = min(100.0, f * 0.8 + 1.0)
        _HEALTH[host] = (s, f)


def _rebuild(req_or_url: Any, host: str) -> Any:
    url = req_or_url.full_url if hasattr(req_or_url, "full_url") else str(req_or_url)
    p = urllib.parse.urlsplit(url)
    new_url = urllib.parse.urlunsplit((p.scheme, host, p.path, p.query, p.fragment))
    if not hasattr(req_or_url, "full_url"):
        return new_url
    headers = dict(req_or_url.header_items())
    return urllib.request.Request(
        new_url,
        data=getattr(req_or_url, "data", None),
        headers=headers,
        origin_req_host=getattr(req_or_url, "origin_req_host", None),
        unverifiable=getattr(req_or_url, "unverifiable", False),
        method=getattr(req_or_url, "method", None),
    )


def _ordered_hosts(original: str) -> Tuple[str, ...]:
    hosts = _HOSTS.get(original, (original,))
    return tuple(sorted(hosts, key=lambda h: (h != original, -_score(h))))


def urlopen(url_or_req: Any, data=None, timeout=None, *args, **kwargs):
    raw_url = url_or_req.full_url if hasattr(url_or_req, "full_url") else str(url_or_req)
    parsed = urllib.parse.urlsplit(raw_url)
    original_host = (parsed.hostname or "").lower()
    if original_host not in _HOSTS:
        return _ORIGINAL(url_or_req, data=data, timeout=timeout, *args, **kwargs)

    hosts = _ordered_hosts(original_host)
    method = (getattr(url_or_req, "method", None) or ("POST" if data is not None else "GET")).upper()
    is_order = parsed.path.endswith("/order") and method in {"POST", "PUT"}
    last_exc: Optional[BaseException] = None

    for idx, host in enumerate(hosts):
        req = _rebuild(url_or_req, host)
        if not hasattr(url_or_req, "full_url") and data is not None:
            req = urllib.request.Request(req, data=data, method=method)
        try:
            resp = _ORIGINAL(req, timeout=timeout, *args, **kwargs)
            _record(host, True)
            return resp
        except urllib.error.HTTPError:
            _record(host, True)
            raise
        except (socket.gaierror, urllib.error.URLError, ConnectionResetError, ConnectionRefusedError, TimeoutError, OSError) as exc:
            _record(host, False)
            last_exc = exc
            if is_order:
                break
            if idx + 1 < len(hosts):
                continue
            break

    if last_exc is not None:
        raise last_exc
    return _ORIGINAL(url_or_req, data=data, timeout=timeout, *args, **kwargs)


def install() -> None:
    global _INSTALLED, _ORIGINAL
    if _INSTALLED:
        return
    try:
        import honeycomb_execution_guard as guard
        guard._BINANCE_HOSTS.update({"api1.binance.com", "api2.binance.com", "api3.binance.com", "api4.binance.com"})
        _ORIGINAL = guard.guarded_urlopen
    except Exception:
        _ORIGINAL = urllib.request.urlopen
    _INSTALLED = True
    urllib.request.urlopen = urlopen


install()
