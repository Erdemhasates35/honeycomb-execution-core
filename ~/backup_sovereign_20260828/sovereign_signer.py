#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SOVEREIGN PRO v3.0 — α-Signed Request Kernel
Binance Futures USDT-M / COIN-M için deterministik HMAC-SHA256 imzalama.
"""

import hmac
import hashlib
import time
import urllib.parse
import urllib.request
import urllib.error
import json
from typing import Dict, Any, Optional


class SovereignSigner:
    """Binance Futures için production imzalama + istek motoru."""

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        base_url: str = "https://fapi.binance.com",
        recv_window: int = 10000,
    ):
        self.key = api_key.strip()
        self.secret = api_secret.strip().encode("utf-8")
        self.base = base_url.rstrip("/")
        self.recv = recv_window
        self._offset = 0  # sunucu-istemci saat farkı (ms)
        self.sync_time()

    def sync_time(self) -> None:
        """Saat senkronizasyonu — -1021/-1022 hatalarını önler."""
        try:
            data = self._raw("GET", "/fapi/v1/time", {}, signed=False)
            server = int(data["serverTime"])
            self._offset = server - int(time.time() * 1000)
        except Exception:
            self._offset = 0

    def _sign(self, params: Dict[str, Any]) -> str:
        """totalParams → signature. Python 3.7+ dict insertion order kullanılır."""
        clean = {k: str(v) for k, v in params.items() if v is not None}
        qs = urllib.parse.urlencode(clean, doseq=True)
        sig = hmac.new(self.secret, qs.encode("utf-8"), hashlib.sha256).hexdigest()
        return qs + "&signature=" + sig

    def _raw(
        self,
        method: str,
        path: str,
        params: Optional[Dict] = None,
        signed: bool = False,
        retries: int = 3,
    ) -> Dict:
        params = dict(params or {})
        if signed:
            params["timestamp"] = int(time.time() * 1000) + self._offset
            params["recvWindow"] = self.recv
            body = self._sign(params)
        else:
            body = urllib.parse.urlencode(
                {k: str(v) for k, v in params.items()}, doseq=True
            )

        url = self.base + path
        data = None
        if method.upper() == "GET":
            if body:
                url += "?" + body
        else:
            data = body.encode("utf-8") if body else None

        headers = {
            "X-MBX-APIKEY": self.key,
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "SOVEREIGN-PRO-v3.0-α",
        }

        last_err = None
        for attempt in range(retries):
            try:
                req = urllib.request.Request(
                    url, data=data, headers=headers, method=method.upper()
                )
                with urllib.request.urlopen(req, timeout=12) as resp:
                    raw = resp.read().decode("utf-8")
                    return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as e:
                raw = e.read().decode() if e.fp else str(e)
                try:
                    err = json.loads(raw)
                except Exception:
                    err = {"code": e.code, "msg": raw}
                code = err.get("code")
                if code in (-1021, -1022):
                    self.sync_time()
                    last_err = RuntimeError(f"sig/time {err}")
                    time.sleep(0.15 * (attempt + 1))
                    continue
                if code == -2015:
                    raise RuntimeError(
                        "API key geçersiz / IP kısıtlı / yetki eksik (-2015)"
                    )
                raise RuntimeError(f"HTTP {e.code}: {err}")
            except (
                urllib.error.URLError,
                ConnectionResetError,
                TimeoutError,
                OSError,
            ) as e:
                last_err = e
                time.sleep(0.3 * (attempt + 1))
        raise RuntimeError(f"{retries} denemeden sonra başarısız: {last_err}")

    # ── Canlı emir metodları ──────────────────────────────────────────────────

    def set_leverage(self, symbol: str, leverage: int) -> Dict:
        return self._raw(
            "POST",
            "/fapi/v1/leverage",
            {"symbol": symbol.upper(), "leverage": int(leverage)},
            signed=True,
        )

    def set_margin_type(self, symbol: str, isolated: bool = True) -> Dict:
        mt = "ISOLATED" if isolated else "CROSSED"
        try:
            return self._raw(
                "POST",
                "/fapi/v1/marginType",
                {"symbol": symbol.upper(), "marginType": mt},
                signed=True,
            )
        except RuntimeError as e:
            if "No need to change" in str(e) or "not modified" in str(e).lower():
                return {"msg": "already set"}
            raise

    def place_market(
        self,
        symbol: str,
        side: str,
        quantity: float,
        position_side: Optional[str] = None,
        reduce_only: bool = False,
    ) -> Dict:
        params = {
            "symbol": symbol.upper(),
            "side": side.upper(),  # BUY / SELL
            "type": "MARKET",
            "quantity": quantity,
        }
        if position_side:
            params["positionSide"] = position_side.upper()
        if reduce_only and not position_side:
            params["reduceOnly"] = "true"
        return self._raw("POST", "/fapi/v1/order", params, signed=True)

    def balance(self) -> float:
        data = self._raw("GET", "/fapi/v2/balance", {}, signed=True)
        for a in data:
            if a.get("asset") == "USDT":
                return float(a.get("availableBalance") or a.get("balance") or 0)
        return 0.0

    def position_risk(self, symbol: str = None) -> list:
        p = {"symbol": symbol.upper()} if symbol else {}
        return self._raw("GET", "/fapi/v2/positionRisk", p, signed=True)
