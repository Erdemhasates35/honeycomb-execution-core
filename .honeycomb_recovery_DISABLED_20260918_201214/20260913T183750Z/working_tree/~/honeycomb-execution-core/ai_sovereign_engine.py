#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI SOVEREIGN ENGINE v2.0 — α-Coupling Production
- 10 ajanlı multi-agent
- Diğer motorlardan tamamen bağımsız
- Algo Order TP/SL
- LIVE_ARMED korumalı
- Circuit-breaker + time-sync + güvenli qty
- α-matematikli özellikler
- Web UI telemetri hazır
"""

import os
import time
import json
import math
import hmac
import hashlib
import logging
import threading
import urllib.parse
import urllib.request
import urllib.error
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field
from collections import deque

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# ─────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [AI-SOVEREIGN] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("AI_Sovereign_Engine")

# ─────────────────────────────────────────────────────────────
# ENV & CONSTANTS (α-hassasiyet)
# ─────────────────────────────────────────────────────────────
ALPHA = 0.00729735256

USE_TESTNET = os.getenv("USE_TESTNET", os.getenv("HONEYCOMB_MODE", "TESTNET")).upper() in (
    "TRUE", "1", "TESTNET", "YES"
)
LIVE_ARMED = os.getenv("LIVE_ARMED", "0").strip() in ("1", "true", "TRUE", "yes")

API_KEY = (
    os.getenv("BINANCE_TESTNET_API_KEY" if USE_TESTNET else "BINANCE_API_KEY")
    or os.getenv("BINANCE_API_KEY")
    or ""
).strip().replace('"', "").replace("'", "")
API_SECRET = (
    os.getenv("BINANCE_TESTNET_SECRET" if USE_TESTNET else "BINANCE_SECRET_KEY")
    or os.getenv("BINANCE_SECRET_KEY")
    or os.getenv("BINANCE_SECRET")
    or os.getenv("BINANCE_API_SECRET")
    or ""
).strip().replace('"', "").replace("'", "")

BASE_URL = (
    os.getenv("BINANCE_TESTNET_URL", "https://testnet.binancefuture.com")
    if USE_TESTNET
    else os.getenv("BINANCE_BASE_URL", os.getenv("BINANCE_FUTURES_URL", "https://fapi.binance.com"))
).rstrip("/")

FEE_RATE = float(os.getenv("FEE_RATE", "0.0004"))
MAX_LEVERAGE = int(float(os.getenv("TESTNET_LEVERAGE", os.getenv("MAX_LEVERAGE", "20"))))
RISK_PER_TRADE = float(os.getenv("TESTNET_RISK", os.getenv("LIVE_RISK", "0.05")))
TP_PCT = float(os.getenv("TESTNET_TP_M", "1.2")) / 100.0
SL_PCT = float(os.getenv("TESTNET_SL_P", "0.8")) / 100.0
SYMBOLS = [s.strip() for s in os.getenv("SOVEREIGN_SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT").split(",") if s.strip()]
RECV_WINDOW = int(os.getenv("RECV_WINDOW", "8000"))
CYCLE_SEC = int(os.getenv("SOVEREIGN_CYCLE_SEC", "25"))
AI_THRESHOLD = int(os.getenv("AI_CONFIDENCE_THRESHOLD", "62"))
MIN_NOTIONAL = 6.0

OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
AI_MODEL = os.getenv("AI_MODEL_ID", "google/gemini-flash-1.5")

# ─────────────────────────────────────────────────────────────
# CORE KERNEL (bağımsız, takılmaz)
# ─────────────────────────────────────────────────────────────
class CoreKernel:
    def __init__(self):
        self._time_offset = 0
        self._fail_count = 0
        self._circuit_open_until = 0.0
        self._lock = threading.Lock()

    def sync_time(self) -> None:
        try:
            data = self._raw_http("GET", "/fapi/v1/time", {}, signed=False)
            server = int(data["serverTime"])
            self._time_offset = server - int(time.time() * 1000)
            logger.info("TIME SYNC offset=%d ms", self._time_offset)
        except Exception as e:
            logger.warning("TIME SYNC FAIL: %s", e)
            self._time_offset = 0

    def _sign(self, params: Dict[str, Any]) -> str:
        clean = {k: str(v) for k, v in params.items() if v is not None}
        qs = urllib.parse.urlencode(clean, doseq=True)
        sig = hmac.new(API_SECRET.encode("utf-8"), qs.encode("utf-8"), hashlib.sha256).hexdigest()
        return qs + "&signature=" + sig

    def _raw_http(self, method: str, endpoint: str, params: Dict, signed: bool = True) -> Any:
        if signed and (not API_KEY or not API_SECRET):
            raise RuntimeError("API_KEY / API_SECRET eksik veya format bozuk")

        params = dict(params or {})
        if signed:
            params["timestamp"] = int(time.time() * 1000) + self._time_offset
            params["recvWindow"] = RECV_WINDOW
            body = self._sign(params)
        else:
            body = urllib.parse.urlencode({k: str(v) for k, v in params.items()}, doseq=True)

        url = BASE_URL + endpoint
        data = None
        headers = {
            "X-MBX-APIKEY": API_KEY,
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "AI-SOVEREIGN/2.0",
        }
        if method.upper() == "GET":
            if body:
                url = url + "?" + body
        else:
            data = body.encode("utf-8") if body else None

        req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
        with urllib.request.urlopen(req, timeout=11) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}

    def http(self, method: str, endpoint: str, params: Optional[Dict] = None, signed: bool = True, retries: int = 4) -> Any:
        now = time.time()
        if now < self._circuit_open_until:
            raise RuntimeError(f"CIRCUIT OPEN ({self._circuit_open_until - now:.1f}s)")

        last_err = None
        for attempt in range(retries):
            try:
                result = self._raw_http(method, endpoint, params or {}, signed=signed)
                self._fail_count = 0
                return result
            except urllib.error.HTTPError as e:
                raw = e.read().decode() if e.fp else str(e)
                try:
                    err = json.loads(raw)
                except Exception:
                    err = {"code": e.code, "msg": raw}
                code = err.get("code")
                if code in (-1021, -1022):
                    self.sync_time()
                    time.sleep(0.25 * (attempt + 1))
                    last_err = RuntimeError(f"sig/time: {err}")
                    continue
                if code == -2015:
                    self._fail_count += 3
                    raise RuntimeError("API key invalid / IP restricted (-2015)")
                if code == -4120:
                    raise RuntimeError("Algo Order endpoint gerekli (-4120)")
                last_err = RuntimeError(f"HTTP {e.code}: {err}")
            except Exception as e:
                last_err = e
                time.sleep(0.35 * (attempt + 1))

            self._fail_count += 1
            if self._fail_count >= 8:
                self._circuit_open_until = time.time() + 25
                logger.error("CIRCUIT BREAKER 25s açıldı")
                self._fail_count = 0

        raise RuntimeError(f"request failed: {last_err}")

kernel = CoreKernel()

# ─────────────────────────────────────────────────────────────
# ALPHA ENGINE (matematiksel özellikler)
# ─────────────────────────────────────────────────────────────
class AlphaEngine:
    @staticmethod
    def decay_score(raw: float, age_sec: float, tau: float = 180.0) -> float:
        return raw * math.exp(-ALPHA * age_sec / tau)

    @staticmethod
    def liquidity_vacuum(bid: float, ask: float, funding: float, fmean: float = 0.0001) -> float:
        imb = (bid - ask) / (bid + ask + 1e-12)
        return imb + 12.0 * (funding - fmean)

    @staticmethod
    def alpha_leverage(max_lev: float, realized_vol: float) -> float:
        return max(1.0, max_lev * (ALPHA / (realized_vol + ALPHA)))

    @staticmethod
    def cost_of_capital_veto(tech: float, veto_conf: float, lam: float = 1.8) -> float:
        penalty = lam * veto_conf * ALPHA * 100
        return max(0.0, tech - penalty)

    @staticmethod
    def toxic_flow(agg_buy: float, agg_sell: float, total: float) -> float:
        if total < 1e-9:
            return 0.0
        return (agg_buy - agg_sell) / total

# ─────────────────────────────────────────────────────────────
# 10 AJAN
# ─────────────────────────────────────────────────────────────
@dataclass
class AgentVote:
    name: str
    direction: str          # LONG / SHORT / FLAT
    confidence: float       # 0-100
    weight: float = 1.0
    reason: str = ""

class AgentRegistry:
    def __init__(self):
        self.agents = [
            "fin_alpha", "fin_beta", "risk_guardian", "quant_validator",
            "liquidity_hunter", "vol_scaler", "toxic_filter",
            "regime_reader", "cost_accountant", "meta_orchestrator"
        ]

    def vote_all(self, symbol: str, price: float, rsi: float, ema_trend: str,
                 vacuum: float, toxic: float, regime: str) -> List[AgentVote]:
        votes = []

        # 1. fin_alpha – momentum
        conf = 70 if ema_trend == "UP" and rsi < 68 else 35
        votes.append(AgentVote("fin_alpha", "LONG" if ema_trend == "UP" else "SHORT", conf, 1.1, "EMA momentum"))

        # 2. fin_beta – mean reversion
        conf = 65 if rsi > 72 else (65 if rsi < 28 else 30)
        direction = "SHORT" if rsi > 72 else ("LONG" if rsi < 28 else "FLAT")
        votes.append(AgentVote("fin_beta", direction, conf, 0.9, "RSI extreme"))

        # 3. risk_guardian – veto odaklı
        conf = 80 if rsi > 75 or rsi < 25 else 40
        votes.append(AgentVote("risk_guardian", "FLAT", conf, 1.3, "Aşırı bölge koruması"))

        # 4. quant_validator
        conf = 55 if abs(rsi - 50) > 15 else 25
        votes.append(AgentVote("quant_validator", ema_trend, conf, 1.0, "İstatistiksel sapma"))

        # 5. liquidity_hunter
        conf = min(90, abs(vacuum) * 120)
        direction = "LONG" if vacuum > 0.35 else ("SHORT" if vacuum < -0.35 else "FLAT")
        votes.append(AgentVote("liquidity_hunter", direction, conf, 1.2, f"Vacuum={vacuum:.3f}"))

        # 6. vol_scaler (sadece bilgi)
        votes.append(AgentVote("vol_scaler", "FLAT", 50, 0.7, "Vol ölçekleme hazır"))

        # 7. toxic_filter
        conf = 85 if abs(toxic) > 0.65 else 20
        votes.append(AgentVote("toxic_filter", "FLAT" if abs(toxic) > 0.65 else ema_trend, conf, 1.4, f"Toxic={toxic:.3f}"))

        # 8. regime_reader
        conf = 60 if regime in ("TREND_UP", "TREND_DOWN") else 35
        direction = "LONG" if regime == "TREND_UP" else ("SHORT" if regime == "TREND_DOWN" else "FLAT")
        votes.append(AgentVote("regime_reader", direction, conf, 1.0, regime))

        # 9. cost_accountant
        votes.append(AgentVote("cost_accountant", "FLAT", 45, 0.8, "Ücret farkındalığı"))

        # 10. meta_orchestrator – ağırlıklı özet
        long_score = sum(v.confidence * v.weight for v in votes if v.direction == "LONG")
        short_score = sum(v.confidence * v.weight for v in votes if v.direction == "SHORT")
        flat_score = sum(v.confidence * v.weight for v in votes if v.direction == "FLAT")
        if long_score > short_score and long_score > flat_score:
            final_dir, final_conf = "LONG", min(95, long_score / 8)
        elif short_score > long_score and short_score > flat_score:
            final_dir, final_conf = "SHORT", min(95, short_score / 8)
        else:
            final_dir, final_conf = "FLAT", min(95, flat_score / 8)
        votes.append(AgentVote("meta_orchestrator", final_dir, final_conf, 1.5, "Ağırlıklı karar"))

        return votes

# ─────────────────────────────────────────────────────────────
# ORDER EXECUTOR (güvenli + Algo Order)
# ─────────────────────────────────────────────────────────────
class OrderExecutor:
    def __init__(self, kernel: CoreKernel):
        self.k = kernel
        self.open_meta: Dict[str, Any] = {}

    def safe_qty(self, balance: float, price: float, leverage: float, step: float = 0.001) -> Tuple[float, float]:
        risk_usdt = balance * RISK_PER_TRADE
        notional = risk_usdt * leverage
        if notional < MIN_NOTIONAL:
            return 0.0, 0.0
        qty = (notional * (1 - FEE_RATE * 2)) / price
        qty = math.floor(qty / step) * step
        if qty * price < MIN_NOTIONAL:
            return 0.0, 0.0
        return round(qty, 6), notional

    def set_leverage(self, symbol: str, lev: int) -> bool:
        try:
            self.k.http("POST", "/fapi/v1/leverage", {"symbol": symbol, "leverage": lev})
            return True
        except Exception as e:
            logger.error("LEVERAGE FAIL %s: %s", symbol, e)
            return False

    def place_market(self, symbol: str, side: str, qty: float) -> Optional[Dict]:
        if not LIVE_ARMED and not USE_TESTNET:
            logger.warning("LIVE_ARMED=0 → emir gönderilmedi (sadece simülasyon)")
            return {"orderId": "SIM", "status": "FILLED", "avgPrice": 0}
        try:
            return self.k.http("POST", "/fapi/v1/order", {
                "symbol": symbol,
                "side": side,
                "type": "MARKET",
                "quantity": qty,
            })
        except Exception as e:
            logger.error("MARKET ORDER FAIL: %s", e)
            return None

    def place_algo_protect(self, symbol: str, direction: str, qty: float, tp: float, sl: float):
        """Algo Order API kullan (TAKE_PROFIT_MARKET / STOP_MARKET)"""
        if not LIVE_ARMED and not USE_TESTNET:
            logger.info("PROTECT SIM | TP=%.4f SL=%.4f", tp, sl)
            return
        tp_side = "SELL" if direction == "LONG" else "BUY"
        sl_side = "SELL" if direction == "LONG" else "BUY"
        try:
            # Algo Order endpoint
            self.k.http("POST", "/fapi/v1/algoOrder", {
                "symbol": symbol,
                "side": tp_side,
                "type": "TAKE_PROFIT_MARKET",
                "algoType": "CONDITIONAL",
                "triggerPrice": str(round(tp, 4)),
                "quantity": str(qty),
                "workingType": "MARK_PRICE",
                "reduceOnly": "true",
            })
            self.k.http("POST", "/fapi/v1/algoOrder", {
                "symbol": symbol,
                "side": sl_side,
                "type": "STOP_MARKET",
                "algoType": "CONDITIONAL",
                "triggerPrice": str(round(sl, 4)),
                "quantity": str(qty),
                "workingType": "MARK_PRICE",
                "reduceOnly": "true",
            })
            logger.info("ALGO PROTECT OK | %s TP=%.4f SL=%.4f", symbol, tp, sl)
        except Exception as e:
            logger.error("ALGO PROTECT FAIL %s: %s", symbol, e)
            # Fallback klasik (testnet için)
            try:
                self.k.http("POST", "/fapi/v1/order", {
                    "symbol": symbol, "side": tp_side, "type": "TAKE_PROFIT_MARKET",
                    "stopPrice": str(round(tp, 4)), "quantity": qty,
                    "workingType": "MARK_PRICE", "reduceOnly": "true"
                })
                self.k.http("POST", "/fapi/v1/order", {
                    "symbol": symbol, "side": sl_side, "type": "STOP_MARKET",
                    "stopPrice": str(round(sl, 4)), "quantity": qty,
                    "workingType": "MARK_PRICE", "reduceOnly": "true"
                })
                logger.info("FALLBACK PROTECT OK")
            except Exception as e2:
                logger.error("FALLBACK PROTECT FAIL: %s", e2)

# ─────────────────────────────────────────────────────────────
# TELEMETRY (Web UI için)
# ─────────────────────────────────────────────────────────────
class TelemetryBridge:
    def __init__(self):
        self.state = {
            "status": "starting",
            "mode": "TESTNET" if USE_TESTNET else "LIVE",
            "live_armed": LIVE_ARMED,
            "last_cycle": 0,
            "open_positions": {},
            "last_votes": [],
            "equity": 0.0,
            "errors": deque(maxlen=20),
        }
        self.lock = threading.Lock()

    def update(self, **kwargs):
        with self.lock:
            self.state.update(kwargs)
            self.state["last_cycle"] = time.time()

    def snapshot(self) -> Dict:
        with self.lock:
            return dict(self.state)

telemetry = TelemetryBridge()

# ─────────────────────────────────────────────────────────────
# ANA DÖNGÜ
# ─────────────────────────────────────────────────────────────
executor = OrderExecutor(kernel)
agents = AgentRegistry()
alpha = AlphaEngine()

def get_balance() -> float:
    try:
        acc = kernel.http("GET", "/fapi/v2/account", {})
        assets = acc.get("assets") or []
        usdt = next((a for a in assets if a.get("asset") == "USDT"), None)
        return float(usdt.get("availableBalance") or usdt.get("walletBalance") or 0) if usdt else 0.0
    except Exception as e:
        logger.error("BALANCE ERR: %s", e)
        return 0.0

def get_market_data(symbol: str) -> Dict[str, Any]:
    ticker = kernel.http("GET", "/fapi/v1/ticker/price", {"symbol": symbol}, signed=False)
    price = float(ticker["price"])
    klines = kernel.http("GET", "/fapi/v1/klines", {"symbol": symbol, "interval": "15m", "limit": 40}, signed=False)
    closes = [float(k[4]) for k in klines]
    ema9 = sum(closes[-9:]) / 9
    ema21 = sum(closes[-21:]) / 21
    ema_trend = "UP" if ema9 > ema21 else "DOWN"
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains = [d for d in deltas[-14:] if d > 0]
    losses = [-d for d in deltas[-14:] if d < 0]
    ag = sum(gains) / 14 if gains else 0.0
    al = sum(losses) / 14 if losses else 1e-9
    rsi = 100 - (100 / (1 + ag / al))
    # basit rejim
    regime = "TREND_UP" if ema_trend == "UP" and rsi > 55 else ("TREND_DOWN" if ema_trend == "DOWN" and rsi < 45 else "RANGE")
    return {"price": price, "rsi": rsi, "ema_trend": ema_trend, "regime": regime, "closes": closes}

def run_cycle():
    balance = get_balance()
    telemetry.update(equity=balance, status="scanning")
    logger.info("CYCLE | balance=%.4f | armed=%s | mode=%s", balance, LIVE_ARMED, "TESTNET" if USE_TESTNET else "LIVE")

    for symbol in SYMBOLS:
        try:
            # Açık pozisyon var mı?
            positions = kernel.http("GET", "/fapi/v2/positionRisk", {"symbol": symbol})
            open_pos = [p for p in positions if abs(float(p.get("positionAmt") or 0)) > 1e-8]
            if open_pos:
                p = open_pos[0]
                logger.info("HOLD %s | amt=%s entry=%.4f uPnL=%.4f", symbol, p.get("positionAmt"), float(p.get("entryPrice") or 0), float(p.get("unRealizedProfit") or 0))
                continue

            md = get_market_data(symbol)
            price, rsi, ema_trend, regime = md["price"], md["rsi"], md["ema_trend"], md["regime"]

            # Basit vacuum & toxic (gerçek orderbook için genişletilebilir)
            vacuum = alpha.liquidity_vacuum(1.0, 1.0, 0.0001)  # placeholder, gerçek book ile değiştir
            toxic = 0.0

            votes = agents.vote_all(symbol, price, rsi, ema_trend, vacuum, toxic, regime)
            meta = next(v for v in votes if v.name == "meta_orchestrator")
            direction, confidence = meta.direction, meta.confidence

            logger.info("SIGNAL %s | %s conf=%.1f | RSI=%.1f EMA=%s regime=%s", symbol, direction, confidence, rsi, ema_trend, regime)
            telemetry.update(last_votes=[{"name": v.name, "dir": v.direction, "conf": v.confidence} for v in votes])

            if direction == "FLAT" or confidence < AI_THRESHOLD:
                logger.info("SKIP %s | conf=%.1f < %d veya FLAT", symbol, confidence, AI_THRESHOLD)
                continue

            # Adaptif kaldıraç
            vol = abs(md["closes"][-1] - md["closes"][-5]) / md["closes"][-5] if len(md["closes"]) > 5 else 0.01
            lev = int(alpha.alpha_leverage(MAX_LEVERAGE, vol))
            lev = max(1, min(lev, MAX_LEVERAGE))

            qty, notional = executor.safe_qty(balance, price, lev)
            if qty <= 0:
                logger.warning("SKIP %s | qty yetersiz", symbol)
                continue

            if not executor.set_leverage(symbol, lev):
                continue

            side = "BUY" if direction == "LONG" else "SELL"
            tp = price * (1 + TP_PCT) if direction == "LONG" else price * (1 - TP_PCT)
            sl = price * (1 - SL_PCT) if direction == "LONG" else price * (1 + SL_PCT)

            logger.info("ORDER %s %s qty=%.6f lev=%dx notional=%.2f TP=%.4f SL=%.4f", direction, symbol, qty, lev, notional, tp, sl)

            order = executor.place_market(symbol, side, qty)
            if order and order.get("status") in ("FILLED", "NEW", "PARTIALLY_FILLED"):
                avg = float(order.get("avgPrice") or price)
                logger.info("FILLED %s id=%s avg=%.4f", symbol, order.get("orderId"), avg)
                executor.open_meta[symbol] = {"side": direction, "entry": avg, "qty": qty, "ts": time.time()}
                executor.place_algo_protect(symbol, direction, qty, tp, sl)
            else:
                logger.error("ORDER REJECT %s: %s", symbol, order)

        except Exception as e:
            logger.error("SYMBOL ERR %s: %s", symbol, e)
            telemetry.state["errors"].append(str(e))

def main():
    if not API_KEY or not API_SECRET:
        logger.error("KRİTİK: API key/secret eksik veya boş. .env kontrol et.")
        return

    kernel.sync_time()
    logger.info(
        "ONLINE v2.0 | mode=%s armed=%s symbols=%s lev_max=%dx cycle=%ds threshold=%d",
        "TESTNET" if USE_TESTNET else "LIVE", LIVE_ARMED, SYMBOLS, MAX_LEVERAGE, CYCLE_SEC, AI_THRESHOLD
    )
    telemetry.update(status="online")

    while True:
        try:
            run_cycle()
            time.sleep(CYCLE_SEC)
        except KeyboardInterrupt:
            logger.info("Durduruldu.")
            telemetry.update(status="stopped")
            break
        except Exception as e:
            logger.error("LOOP ERR: %s", e)
            telemetry.state["errors"].append(str(e))
            time.sleep(12)

if __name__ == "__main__":
    main()
