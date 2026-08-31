#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Helix Sovereign ULTRA v2.5 - Dynamic Live Scalper
- Sovereign Mode: LIVE (Binance Futures REST Order Execution)
- Margin: 10% Available Balance per trade (Max 5 trades = 50% max allocation)
- Dynamic Leverage: 10x to 50x scaled by signal confidence
- Order Type: LIMIT (Maker Fee Optimization @ 0.02%)
"""

from __future__ import annotations

import os
import time
import hmac
import hashlib
import urllib.parse
import json
import logging
import threading
import requests
import numpy as np
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
from flask import Flask, jsonify

# =============================================================================
# ENVIRONMENT & CONFIGURATION
# =============================================================================

ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

def load_env(path: str) -> dict[str, str]:
    env: dict[str, str] = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().split("#")[0].strip().strip('"').strip("'")
    return env

ENV = load_env(ENV_PATH)

MODE = ENV.get("SOVEREIGN_MODE", "DRYRUN").upper()
SYMBOLS = [s.strip().upper() for s in ENV.get("SOVEREIGN_SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT").split(",") if s.strip()]
RISK_RATIO = float(ENV.get("RISK_PER_TRADE_RATIO", "0.10"))
MAX_OPEN = int(ENV.get("MAX_CONCURRENT", "5"))
MIN_LEV = float(ENV.get("MIN_LEVERAGE", "10.0"))
MAX_LEV = float(ENV.get("MAX_LEVERAGE", "50.0"))
INTERVAL = int(ENV.get("AUTO_INTERVAL_SEC", "6"))
PORT = int(ENV.get("LIVE_PORT", "8082"))

BINANCE_API_KEY = ENV.get("BINANCE_API_KEY", "")
BINANCE_SECRET = ENV.get("BINANCE_SECRET_KEY", "")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [ULTRA-LIVE] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.info

# =============================================================================
# BINANCE FUTURES API CLIENT (LIVE EXECUTION)
# =============================================================================

class BinanceFuturesClient:
    def __init__(self, api_key: str, secret: str):
        self.api_key = api_key
        self.secret = secret
        self.base = "https://fapi.binance.com"
        self.session = requests.Session()
        self.session.headers.update({"X-MBX-APIKEY": api_key})

    def _sign(self, params: dict) -> str:
        query = urllib.parse.urlencode(sorted(params.items()))
        return hmac.new(self.secret.encode(), query.encode(), hashlib.sha256).hexdigest()

    def request(self, method: str, endpoint: str, params: Optional[dict] = None, signed: bool = False) -> Any:
        url = f"{self.base}{endpoint}"
        params = params or {}
        if signed:
            params["timestamp"] = int(time.time() * 1000)
            params["recvWindow"] = 5000
            params["signature"] = self._sign(params)
        try:
            if method == "GET":
                r = self.session.get(url, params=params, timeout=8)
            else:
                r = self.session.post(url, data=params, timeout=8)
            return r.json()
        except Exception as e:
            log(f"API Hatasi ({endpoint}): {e}")
            return {}

    def get_usdt_balance(self) -> float:
        res = self.request("GET", "/fapi/v2/balance", signed=True)
        if isinstance(res, list):
            for asset in res:
                if asset.get("asset") == "USDT":
                    return float(asset.get("availableBalance", 0.0))
        return 0.0

    def get_open_positions(self) -> List[dict]:
        res = self.request("GET", "/fapi/v2/positionRisk", signed=True)
        positions = []
        if isinstance(res, list):
            for p in res:
                amt = float(p.get("positionAmt", 0.0))
                if abs(amt) > 0:
                    positions.append(p)
        return positions

    def set_leverage(self, symbol: str, leverage: int) -> bool:
        res = self.request("POST", "/fapi/v1/leverage", {"symbol": symbol, "leverage": leverage}, signed=True)
        return "leverage" in res

    def post_limit_order(self, symbol: str, side: str, qty: float, price: float) -> dict:
        params = {
            "symbol": symbol,
            "side": side,
            "type": "LIMIT",
            "timeInForce": "GTC",
            "quantity": f"{qty:.3f}",
            "price": f"{price:.4f}",
        }
        return self.request("POST", "/fapi/v1/order", params, signed=True)

    def get_klines(self, symbol: str, interval: str = "5m", limit: int = 100) -> dict:
        data = self.request("GET", "/fapi/v1/klines", {"symbol": symbol, "interval": interval, "limit": limit})
        if not data or not isinstance(data, list):
            return {}
        return {
            "o": np.array([float(x[1]) for x in data]),
            "h": np.array([float(x[2]) for x in data]),
            "l": np.array([float(x[3]) for x in data]),
            "c": np.array([float(x[4]) for x in data]),
            "v": np.array([float(x[5]) for x in data]),
        }

# =============================================================================
# STRATEGIES & INDICATORS
# =============================================================================

@dataclass
class Signal:
    side: str
    conf: float
    mark: float
    strategy: str
    reason: str

def ema(arr: np.ndarray, p: int) -> float:
    if len(arr) < p: return float(np.mean(arr)) if len(arr) else 0.0
    k = 2.0 / (p + 1)
    v = float(np.mean(arr[:p]))
    for x in arr[p:]: v = x * k + v * (1 - k)
    return v

def rsi(arr: np.ndarray, p: int = 14) -> float:
    if len(arr) < p + 1: return 50.0
    d = np.diff(arr)
    g, l = np.where(d > 0, d, 0), np.where(d < 0, -d, 0)
    ag, al = float(np.mean(g[-p:])), float(np.mean(l[-p:]))
    return 100.0 if al == 0 else 100.0 - (100.0 / (1.0 + ag / al))

class ScalpStrategy:
    def generate(self, symbol: str, mark: float, data: Optional[dict] = None) -> Optional[Signal]:
        if not data or "c" not in data or len(data["c"]) < 30:
            return None
        c = data["c"]
        e9, e21 = ema(c, 9), ema(c, 21)
        r_val = rsi(c)

        score = 50.0
        if e9 > e21: score += 25
        else: score -= 25

        if r_val > 60: score += 20
        elif r_val < 40: score -= 20

        conf = max(0.0, min(100.0, score))
        if conf >= 65.0:
            return Signal("BUY", conf, mark, "E9_21_SCALP", f"Bullish Cross | RSI={r_val:.1f}")
        elif conf <= 35.0:
            return Signal("SELL", 100.0 - conf, mark, "E9_21_SCALP", f"Bearish Cross | RSI={r_val:.1f}")
        return None

# =============================================================================
# ENGINE & DYNAMIC ALLOCATION LOGIC
# =============================================================================

class UltraEngine:
    def __init__(self):
        self.client = BinanceFuturesClient(BINANCE_API_KEY, BINANCE_SECRET)
        self.strategy = ScalpStrategy()

    def calculate_leverage(self, conf: float) -> int:
        """Sinyal güvenine göre 10x ile 50x arasında dinamik kaldıraç üretir."""
        clamped_conf = max(60.0, min(100.0, conf))
        ratio = (clamped_conf - 60.0) / 40.0
        lev = MIN_LEV + ratio * (MAX_LEV - MIN_LEV)
        return int(round(lev))

    def process_live(self):
        active_positions = self.client.get_open_positions() if MODE == "LIVE" else []
        if len(active_positions) >= MAX_OPEN:
            log(f"⚠️ Maksimum pozisyon limitine ulasildi ({len(active_positions)}/{MAX_OPEN}). Yeni emir bekleniyor...")
            return

        balance = self.client.get_usdt_balance() if MODE == "LIVE" else 100.0
        if balance < 5.0 and MODE == "LIVE":
            log("⚠️ Yetersiz kullanılabilir USDT bakiyesi.")
            return

        best_sig: Optional[Signal] = None
        target_symbol = ""

        for symbol in SYMBOLS:
            klines = self.client.get_klines(symbol, "5m", 50)
            if not klines or "c" not in klines or len(klines["c"]) == 0:
                continue
            mark = klines["c"][-1]
            sig = self.strategy.generate(symbol, mark, klines)
            if sig and (best_sig is None or sig.conf > best_sig.conf):
                best_sig = sig
                target_symbol = symbol

        if not best_sig:
            return

        # Dinamik Hesaplamalar
        leverage = self.calculate_leverage(best_sig.conf)
        margin_amount = balance * RISK_RATIO
        notional_size = margin_amount * leverage
        
        # Limit Emir Fiyatı (Piyasa yapıcı komisyonu için milimetrik kayma)
        limit_price = best_sig.mark * 0.9998 if best_sig.side == "BUY" else best_sig.mark * 1.0002
        quantity = notional_size / limit_price

        log(f"🔥 EN YÜKSEK SİNYAL: {target_symbol} | Yön: {best_sig.side} | Güven: %{best_sig.conf:.1f}")
        log(f"📊 Sermaye Tahsisi: ${margin_amount:.2f} (%10) | Dinamik Kaldıraç: {leverage}x | Hacim: ${notional_size:.2f}")

        if MODE == "LIVE":
            self.client.set_leverage(target_symbol, leverage)
            res = self.client.post_limit_order(target_symbol, best_sig.side, quantity, limit_price)
            log(f"🚀 CANLI LIMIT EMIR GÖNDERİLDI: {res}")

    def run(self):
        log(f"⚡ Helix Sovereign ULTRA v2.5 Başlatıldı | Mod: {MODE} | Max Pozisyon: {MAX_OPEN}")
        while True:
            try:
                self.process_live()
            except Exception as e:
                log(f"Hata: {e}")
            time.sleep(INTERVAL)

# =============================================================================
# MAIN ENTRY
# =============================================================================

app = Flask(__name__)
engine = UltraEngine()

@app.route("/")
def index():
    return jsonify({
        "status": "ONLINE",
        "mode": MODE,
        "max_concurrent": MAX_OPEN,
        "risk_ratio": RISK_RATIO,
        "min_lev": MIN_LEV,
        "max_lev": MAX_LEV
    })

if __name__ == "__main__":
    t = threading.Thread(target=lambda: app.run(host="0.0.0.0", port=PORT, use_reloader=False), daemon=True)
    t.start()
    engine.run()
