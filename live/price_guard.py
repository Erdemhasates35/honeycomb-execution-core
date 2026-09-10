#!/usr/bin/env python3
# live/price_guard.py
# α-HONEYCOMB ORDINARYUS PRICE LAYER
# Anayasa 5 + 9: book_mid icra, markPriceKlines öncelik, age kontrolü
# Tüm motorlar (quantum, sovereign, helix, aggressive, lobster, supreme) bunu import eder

import time
import hmac
import hashlib
import urllib.parse
import urllib.request
import json
from typing import Optional, Dict, List, Tuple, Any

# === ANAYASA SABİTLERİ ===
MIN_EDGE          = 0.0005
FEE_RT            = 0.0011          # 2*taker + slip
MAX_KLINE_AGE_SEC = 90              # 1m için güvenli üst
SERVER_TIME_TOL   = 1500

class PriceGuard:
    def __init__(self, api_key: str, api_secret: str, base: str = "https://fapi.binance.com"):
        self.api_key = api_key.strip()
        self.api_secret = api_secret.strip().encode("utf-8")
        self.base = base.rstrip("/")
        self._server_offset = 0
        self._last_sync = 0.0

    def _sign(self, params: Dict[str, Any]) -> str:
        # Anayasa 7: sıralı query-string, signature HARİÇ
        items = sorted((k, str(v)) for k, v in params.items() if v is not None)
        qs = urllib.parse.urlencode(items)
        sig = hmac.new(self.api_secret, qs.encode("utf-8"), hashlib.sha256).hexdigest()
        return qs + "&signature=" + sig

    def _request(self, method: str, path: str, params: Optional[Dict] = None, signed: bool = False) -> Any:
        params = dict(params or {})
        if signed:
            params["timestamp"] = int(time.time() * 1000) + self._server_offset
            params["recvWindow"] = 5000
            body = self._sign(params)
            url = f"{self.base}{path}?{body}"
            req = urllib.request.Request(url, method=method, headers={"X-MBX-APIKEY": self.api_key})
        else:
            qs = urllib.parse.urlencode({k: str(v) for k, v in params.items()})
            url = f"{self.base}{path}?{qs}" if qs else f"{self.base}{path}"
            req = urllib.request.Request(url, method=method)
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.loads(r.read().decode("utf-8"))

    def sync_time(self) -> None:
        try:
            data = self._request("GET", "/fapi/v1/time")
            server = int(data["serverTime"])
            local = int(time.time() * 1000)
            self._server_offset = server - local
            self._last_sync = time.time()
        except Exception:
            pass

    def book_mid(self, symbol: str) -> float:
        """Anayasa 5: İcra fiyatı = bookTicker mid. Ham kline close ASLA kullanılmaz."""
        data = self._request("GET", "/fapi/v1/ticker/bookTicker", {"symbol": symbol.upper()})
        bid = float(data["bidPrice"])
        ask = float(data["askPrice"])
        if bid <= 0 or ask <= 0 or ask < bid:
            raise RuntimeError(f"stale_book {symbol}")
        return (bid + ask) / 2.0

    def fetch_ohlcv(self, symbol: str, interval: str = "1m", limit: int = 100) -> Tuple[List[List[float]], str, float]:
        """
        Anayasa 5 + 9:
        1) markPriceKlines + serverTime penceresi
        2) indexPriceKlines
        3) klines (son çare)
        age_sec kontrolü zorunlu. Stale veri ile emir YASAK.
        Dönüş: (ohlcv, src_name, age_sec)
        """
        if time.time() - self._last_sync > 30:
            self.sync_time()

        end_ms = int(time.time() * 1000) + self._server_offset
        interval_ms = 60_000
        if interval.endswith("m"):
            try:
                interval_ms = int(interval[:-1]) * 60_000
            except Exception:
                interval_ms = 60_000
        start_ms = end_ms - (limit * interval_ms)

        sources = [
            ("mark",  "/fapi/v1/markPriceKlines"),
            ("index", "/fapi/v1/indexPriceKlines"),
            ("kline", "/fapi/v1/klines"),
        ]

        last_err = None
        for src_name, path in sources:
            try:
                params = {
                    "symbol": symbol.upper(),
                    "interval": interval,
                    "startTime": start_ms,
                    "endTime": end_ms,
                    "limit": limit,
                }
                raw = self._request("GET", path, params)
                if not raw or len(raw) < 10:
                    last_err = f"empty_{src_name}"
                    continue

                ohlcv = []
                for row in raw:
                    ohlcv.append([
                        float(row[0]),  # open_time
                        float(row[1]),  # open
                        float(row[2]),  # high
                        float(row[3]),  # low
                        float(row[4]),  # close
                        float(row[5]) if len(row) > 5 else 0.0,
                    ])

                age_sec = (end_ms - ohlcv[-1][0]) / 1000.0
                if age_sec > MAX_KLINE_AGE_SEC:
                    last_err = f"age_too_old src={src_name} age={age_sec:.1f}s"
                    continue

                return ohlcv, src_name, age_sec
            except Exception as e:
                last_err = str(e)
                continue

        raise RuntimeError(f"OHLCV_FAIL {symbol} last={last_err}")

    def edge(self, expected_move: float, price: float) -> float:
        """Anayasa III: edge = (exp_move - P * c) / P"""
        if price <= 0:
            return -1.0
        return (expected_move - price * FEE_RT) / price

    def gate_edge(self, expected_move: float, price: float) -> bool:
        return self.edge(expected_move, price) >= MIN_EDGE
