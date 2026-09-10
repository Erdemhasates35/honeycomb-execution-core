#!/usr/bin/env python3
# live/supreme_engine.py  — α-HONEYCOMB ORDINARYUS SUPREME LIVE ENGINE
# Tüm motorların en iyi özelliklerinin birleşimi + Anayasa 1-20

import os
import time
import math
import json
import sqlite3
import threading
from typing import Dict, List, Optional, Tuple
from live.price_guard import PriceGuard, MIN_EDGE, FEE_RT

# === PARAMETRELER (Anayasa + Pareto) ===
MIN_LEV, MAX_LEV   = 5, 25
RISK_FRAC          = 0.012          # bakiye * risk * L
CAP_NOTIONAL       = 800.0
TP_ATR_MULT        = 1.25
SL_ATR_MULT        = 0.80
PARETO_TOP_K       = 0.20           # top %20 edge
FAIL_BUDGET        = 18             # ardışık fail → kısa mola
MIN_NOTIONAL       = 5.5

class SupremeEngine:
    def __init__(self, api_key: str, api_secret: str, symbols: List[str]):
        self.pg = PriceGuard(api_key, api_secret)
        self.symbols = [s.upper() for s in symbols]
        self.dual = None
        self.fail_streak = 0
        self.lock = threading.Lock()
        self.db = sqlite3.connect("supreme_brain.db", check_same_thread=False)
        self._init_brain()

    def _init_brain(self):
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS evolve (
                symbol TEXT, side TEXT, edge REAL, result TEXT,
                pnl REAL, ts REAL, weight REAL DEFAULT 1.0
            )
        """)
        self.db.commit()

    def _get_dual(self) -> bool:
        if self.dual is None:
            try:
                data = self.pg._request("GET", "/fapi/v1/positionSide/dual", signed=True)
                self.dual = bool(data.get("dualSidePosition", False))
            except Exception:
                self.dual = False
        return self.dual

    def _atr(self, ohlcv: List[List[float]], period: int = 14) -> float:
        if len(ohlcv) < period + 1:
            return 0.0
        trs = []
        for i in range(1, len(ohlcv)):
            h, l, c_prev = ohlcv[i][2], ohlcv[i][3], ohlcv[i-1][4]
            trs.append(max(h - l, abs(h - c_prev), abs(l - c_prev)))
        return sum(trs[-period:]) / period

    def _score(self, ohlcv: List[List[float]]) -> Tuple[float, float, float]:
        """Basit ama sağlam multi-feature score + z + rsi"""
        closes = [x[4] for x in ohlcv]
        if len(closes) < 30:
            return 0.0, 0.0, 50.0
        ret = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes))]
        mean = sum(ret[-20:]) / 20
        var = sum((r - mean)**2 for r in ret[-20:]) / 20
        z = mean / (math.sqrt(var) + 1e-9)
        # RSI
        gains = [max(r, 0) for r in ret[-14:]]
        losses = [max(-r, 0) for r in ret[-14:]]
        avg_g = sum(gains) / 14
        avg_l = sum(losses) / 14 + 1e-9
        rs = avg_g / avg_l
        rsi = 100 - (100 / (1 + rs))
        score = z * 0.6 + (rsi - 50) / 50 * 0.4
        return score, z, rsi

    def scan(self) -> List[Dict]:
        """Pareto top-K edge taraması"""
        candidates = []
        for sym in self.symbols:
            try:
                px = self.pg.book_mid(sym)
                ohlcv, src, age = self.pg.fetch_ohlcv(sym, "1m", 80)
                atr = self._atr(ohlcv)
                score, z, rsi = self._score(ohlcv)
                exp_move = atr * 1.1          # beklenen hareket
                edge = self.pg.edge(exp_move, px)
                if edge < MIN_EDGE:
                    continue
                candidates.append({
                    "symbol": sym,
                    "px": px,
                    "edge": edge,
                    "score": score,
                    "z": z,
                    "rsi": rsi,
                    "atr": atr,
                    "ohlcv_src": src,
                    "age_sec": age,
                })
            except Exception as e:
                continue

        # Pareto: edge sıralı top %20
        candidates.sort(key=lambda x: x["edge"], reverse=True)
        k = max(1, int(len(candidates) * PARETO_TOP_K))
        return candidates[:k]

    def _dynamic_lev(self, conf: float, inv_vol: float) -> int:
        # conf ↑ → L ↑, vol ↑ → L ↓
        base = MIN_LEV + (MAX_LEV - MIN_LEV) * conf
        lev = int(base * (0.7 + 0.3 * inv_vol))
        return max(MIN_LEV, min(MAX_LEV, lev))

    def enter(self, cand: Dict, balance: float) -> Optional[Dict]:
        """Anayasa 1-15 tam uyumlu ENTER"""
        sym = cand["symbol"]
        px = cand["px"]
        atr = cand["atr"]
        edge = cand["edge"]

        if edge < MIN_EDGE:
            return None

        conf = min(1.0, max(0.0, (cand["score"] + 1) / 2))
        inv_vol = 1.0 / (atr / px + 1e-6)
        lev = self._dynamic_lev(conf, inv_vol)

        notional = min(CAP_NOTIONAL, balance * RISK_FRAC * lev)
        if notional < MIN_NOTIONAL:
            return None

        qty = notional / px
        # quantize basit (gerçekte exchange filter kullanılmalı)
        qty = math.floor(qty * 1000) / 1000
        if qty <= 0:
            return None

        side = "BUY" if cand["score"] > 0 else "SELL"
        pos_side = "LONG" if side == "BUY" else "SHORT"
        dual = self._get_dual()

        tp = px + TP_ATR_MULT * atr if side == "BUY" else px - TP_ATR_MULT * atr
        sl = px - SL_ATR_MULT * atr if side == "BUY" else px + SL_ATR_MULT * atr

        # --- GERÇEK EMİR (LiveKernel.place_market benzeri) ---
        # Burada senin mevcut LiveKernel.open_market çağrısı yapılmalı
        # Örnek iskelet (gerçek imza + positionSide zorunlu):
        params = {
            "symbol": sym,
            "side": side,
            "type": "MARKET",
            "quantity": qty,
        }
        if dual:
            params["positionSide"] = pos_side

        # ... imza + POST /fapi/v1/order ...
        # orderId geldiyse:
        # log zorunlu satırlar:
        log = {
            "px_book": px,
            "ohlcv_src": cand["ohlcv_src"],
            "age_sec": cand["age_sec"],
            "score": cand["score"],
            "z": cand["z"],
            "rsi": cand["rsi"],
            "edge": edge,
            "N": notional,
            "M": notional / lev,
            "C": notional * FEE_RT,
            "ROE_tp_est": (TP_ATR_MULT * atr / px - FEE_RT) * lev * 100,
            "ROE_sl_est": (-SL_ATR_MULT * atr / px - FEE_RT) * lev * 100,
            "positionSide": pos_side if dual else "BOTH",
            # "orderId": ...
        }
        print(json.dumps(log, ensure_ascii=False))
        return log

    def run_cycle(self, balance: float):
        if self.fail_streak >= FAIL_BUDGET:
            time.sleep(45)
            self.fail_streak = 0

        top = self.scan()
        for c in top:
            try:
                res = self.enter(c, balance)
                if res:
                    self.fail_streak = 0
                else:
                    self.fail_streak += 1
            except Exception as e:
                self.fail_streak += 1
                print(f"ENTER_FAIL {c['symbol']} {e}")

