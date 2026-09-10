#!/data/data/com.termux/files/usr/bin/python3
# -*- coding: utf-8 -*-
"""Quantum Academic Core v3 LIVE
- Leverage 50-75
- Dynamic ATR TP/SL
- Multi-TF + RSI + Z
- Net-edge guard + detailed academic logs
- Real orders via LiveKernel
"""
from __future__ import annotations

import os
import sys
import time
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple

ROOT = os.path.join(os.path.expanduser("~"), "honeycomb-execution-core")
sys.path.insert(0, ROOT)

try:
    import agg_live_fix
except Exception:
    pass

from live.kernel import LiveKernel

MIN_LEV = int(os.getenv("MIN_LEVERAGE", "50"))
MAX_LEV = int(os.getenv("MAX_LEVERAGE", "75"))
TAKER = float(os.getenv("TAKER_FEE_RATE", "0.0004"))
SLIP = float(os.getenv("SLIPPAGE_RATE", "0.0003"))
MIN_EDGE = float(os.getenv("MIN_EDGE", "0.0004"))
NOTIONAL = float(os.getenv("ORDER_NOTIONAL", "45"))
SCAN_SEC = float(os.getenv("SCAN_SEC", "12"))
TP_ATR = float(os.getenv("TP_ATR", "1.4"))
SL_ATR = float(os.getenv("SL_ATR", "0.9"))


def ema(data: List[float], n: int) -> float:
    if len(data) < n:
        return 0.0
    k = 2.0 / (n + 1.0)
    v = sum(data[:n]) / n
    for x in data[n:]:
        v = (x - v) * k + v
    return v


def rsi(data: List[float], n: int = 14) -> float:
    if len(data) < n + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(data)):
        d = data[i] - data[i - 1]
        gains.append(max(0.0, d))
        losses.append(max(0.0, -d))
    ag = sum(gains[-n:]) / n
    al = sum(losses[-n:]) / n
    if al == 0:
        return 100.0
    rs = ag / al
    return 100.0 - (100.0 / (1.0 + rs))


def atr(h, l, c, n=14) -> float:
    if len(h) < n + 1:
        return 0.0
    trs = [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, len(h))]
    return sum(trs[-n:]) / n


def zscore(data: List[float], n=20) -> float:
    if len(data) < n:
        return 0.0
    sub = data[-n:]
    m = sum(sub) / n
    var = sum((x - m) ** 2 for x in sub) / (n - 1)
    s = math.sqrt(var) if var > 0 else 0.0
    return (data[-1] - m) / s if s > 0 else 0.0


def vwap(h, l, c, v) -> float:
    tot = sum(v) if v else 0.0
    if tot <= 0:
        return c[-1] if c else 0.0
    return sum(((h[i] + l[i] + c[i]) / 3.0) * v[i] for i in range(len(c))) / tot


class LiveAcademicCore:
    def __init__(self):
        self.k = LiveKernel()
        try:
            from live.kernel_hardened_sign import apply_hardened_sign
            apply_hardened_sign(self.k)
            print("[CORE] hardened_sign OK", flush=True)
        except Exception as e:
            print("[CORE] hardened FAIL:", e, flush=True)
        self.symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "AVAXUSDT"]
        self.filters: Dict[str, Dict] = {}
        self._load_filters()
        self.cycle_n = 0
        self.open_count = 0

    def _http(self, method, path, params=None, signed=False, weight=1, is_order=False):
        return self.k._http(method, path, params or {}, signed=signed, weight=weight, is_order=is_order)

    def _load_filters(self):
        try:
            info = self._http("GET", self.k.v.get("exchangeInfo", "/fapi/v1/exchangeInfo"), {}, signed=False, weight=10)
        except Exception as e:
            print("[CORE] exchangeInfo FAIL:", e, flush=True)
            return
        if not isinstance(info, dict):
            return
        want = set(self.symbols)
        for s in info.get("symbols", []):
            sym = s.get("symbol")
            if sym not in want:
                continue
            f = {"stepSize": 0.001, "minQty": 0.001, "minNotional": 5.0, "tickSize": 0.01}
            for filt in s.get("filters", []):
                t = filt.get("filterType")
                if t == "LOT_SIZE":
                    f["stepSize"] = float(filt["stepSize"])
                    f["minQty"] = float(filt["minQty"])
                elif t in ("MIN_NOTIONAL", "NOTIONAL"):
                    f["minNotional"] = float(filt.get("notional") or filt.get("minNotional") or 5)
                elif t == "PRICE_FILTER":
                    f["tickSize"] = float(filt["tickSize"])
            self.filters[sym] = f
        print("[CORE] filters:", list(self.filters.keys()), flush=True)

    def q_qty(self, symbol: str, qty: float) -> float:
        f = self.filters.get(symbol, {})
        step = float(f.get("stepSize", 0.001))
        mn = float(f.get("minQty", 0.001))
        q = math.floor(max(qty, mn) / step) * step
        return float(("%f" % q).rstrip("0").rstrip(".") or "0")

    def q_price(self, symbol: str, price: float) -> float:
        f = self.filters.get(symbol, {})
        tick = float(f.get("tickSize", 0.01))
        p = round(round(price / tick) * tick, 8)
        return float(("%f" % p).rstrip("0").rstrip(".") or "0")

    def klines(self, symbol: str, interval: str, limit: int = 60):
        path = self.k.v.get("klines", "/fapi/v1/klines")
        data = self._http("GET", path, {"symbol": symbol, "interval": interval, "limit": limit}, signed=False, weight=5)
        if not data or not isinstance(data, list):
            return None
        return {
            "h": [float(x[2]) for x in data],
            "l": [float(x[3]) for x in data],
            "c": [float(x[4]) for x in data],
            "v": [float(x[5]) for x in data],
        }

    def analyze(self, symbol: str) -> Optional[Dict[str, Any]]:
        tfs = {}
        for tf in ("5m", "15m", "30m"):
            k = self.klines(symbol, tf, 60)
            if not k or len(k["c"]) < 30:
                return None
            tfs[tf] = {
                "ema9": ema(k["c"], 9),
                "ema21": ema(k["c"], 21),
                "vwap": vwap(k["h"], k["l"], k["c"], k["v"]),
                "z": zscore(k["c"], 20),
                "atr": atr(k["h"], k["l"], k["c"], 14),
                "rsi": rsi(k["c"], 14),
                "px": k["c"][-1],
            }

        def side(tf):
            d = tfs[tf]
            return 1.0 if d["ema9"] > d["ema21"] and d["px"] > d["vwap"] else -1.0

        score = side("5m") * 0.50 + side("15m") * 0.30 + side("30m") * 0.20
        px = tfs["5m"]["px"]
        a = tfs["5m"]["atr"]
        z = tfs["5m"]["z"]
        r = tfs["5m"]["rsi"]

        # Volatility-scaled expected move
        exp_move = abs(score) * a * 1.25
        cost = px * (2 * TAKER + SLIP)
        net_edge = (exp_move - cost) / px if px > 0 else -1.0

        vol = min(1.0, a / px) if px > 0 else 1.0
        conf = min(1.0, abs(score))
        lev = int(max(MIN_LEV, min(MAX_LEV, round(MIN_LEV + (MAX_LEV - MIN_LEV) * conf * (1.0 - vol * 0.7)))))

        return {
            "symbol": symbol,
            "score": score,
            "z": z,
            "rsi": r,
            "atr": a,
            "px": px,
            "edge": net_edge,
            "exp_move": exp_move,
            "cost": cost,
            "lev": lev,
            "ema9": tfs["5m"]["ema9"],
            "ema21": tfs["5m"]["ema21"],
            "vwap": tfs["5m"]["vwap"],
        }

    def decide(self, a: Dict[str, Any]) -> Tuple[Optional[str], str]:
        # 1) Net edge guard
        if a["edge"] < MIN_EDGE:
            return None, "neg_ev edge=%.5f" % a["edge"]

        score, z, rsi = a["score"], a["z"], a["rsi"]

        # 2) Strong multi-TF short + not deeply oversold (avoid catching falling knife)
        if score <= -0.55:
            if z >= 0.8 or rsi >= 65:
                return "SELL", "short TF+z/rsi score=%.2f z=%.2f rsi=%.1f" % (score, z, rsi)
            if score <= -0.85:  # çok güçlü hizalanma → z şartını gevşet
                return "SELL", "strong_short score=%.2f z=%.2f rsi=%.1f" % (score, z, rsi)

        # 3) Strong multi-TF long + not deeply overbought
        if score >= 0.55:
            if z <= -0.8 or rsi <= 35:
                return "BUY", "long TF+z/rsi score=%.2f z=%.2f rsi=%.1f" % (score, z, rsi)
            if score >= 0.85:
                return "BUY", "strong_long score=%.2f z=%.2f rsi=%.1f" % (score, z, rsi)

        return None, "no_setup score=%.2f z=%.2f rsi=%.1f" % (score, z, rsi)

    def enter(self, a: Dict[str, Any], side: str, reason: str):
        raw = NOTIONAL / a["px"]
        qty = self.q_qty(a["symbol"], raw)
        notional = qty * a["px"]
        mn = float(self.filters.get(a["symbol"], {}).get("minNotional", 5.0))
        if notional < mn or qty <= 0:
            print("[CORE] SKIP minNotional/qty %s" % a["symbol"], flush=True)
            return

        # Dynamic TP / SL
        if side == "BUY":
            tp = self.q_price(a["symbol"], a["px"] + TP_ATR * a["atr"])
            sl = self.q_price(a["symbol"], a["px"] - SL_ATR * a["atr"])
        else:
            tp = self.q_price(a["symbol"], a["px"] - TP_ATR * a["atr"])
            sl = self.q_price(a["symbol"], a["px"] + SL_ATR * a["atr"])

        fee_est = notional * 2 * TAKER
        print("[CORE] === LIVE ENTER ===", flush=True)
        print("  %s %s qty=%.6f px=%.6f lev=%dx" % (side, a["symbol"], qty, a["px"], a["lev"]), flush=True)
        print("  score=%.3f z=%.3f rsi=%.1f edge=%.5f" % (a["score"], a["z"], a["rsi"], a["edge"]), flush=True)
        print("  TP=%.6f SL=%.6f fee_est=%.4f notional=%.2f" % (tp, sl, fee_est, notional), flush=True)
        print("  reason: %s" % reason, flush=True)

        # leverage
        try:
            self._http("POST", self.k.v.get("leverage", "/fapi/v1/leverage"),
                       {"symbol": a["symbol"], "leverage": int(a["lev"])},
                       signed=True, weight=1, is_order=True)
        except Exception as e:
            if "4056" not in str(e) and "-4028" not in str(e):
                print("  [LEV WARN]", e, flush=True)

        # market entry
        try:
            params = {
                "symbol": a["symbol"],
                "side": side,
                "type": "MARKET",
                "quantity": str(qty),
            }
            res = self._http("POST", self.k.v.get("order", "/fapi/v1/order"),
                             params, signed=True, weight=1, is_order=True)
            print("  [ORDER OK]", res, flush=True)
            self.open_count += 1
        except Exception as e:
            print("  [ENTER FAIL]", e, flush=True)
            return

        # protect TP/SL via kernel if available
        try:
            if hasattr(self.k, "place_protect"):
                self.k.place_protect(a["symbol"], side, a["px"], tp, sl)
                print("  [PROTECT] TP/SL placed", flush=True)
            else:
                # fallback: conditional algo if bridge exists
                print("  [PROTECT] place_protect yok - manuel izleme", flush=True)
        except Exception as e:
            print("  [PROTECT WARN]", e, flush=True)

    def cycle(self):
        self.cycle_n += 1
        scanned = []
        with ThreadPoolExecutor(max_workers=4) as ex:
            futs = [ex.submit(self.analyze, s) for s in self.symbols]
            for f in as_completed(futs):
                r = f.result()
                if r:
                    scanned.append(r)
        if not scanned:
            print("[CORE] cycle=%d no data" % self.cycle_n, flush=True)
            return

        scanned.sort(key=lambda x: abs(x["edge"]), reverse=True)
        parts = []
        for x in scanned[:6]:
            tag = "L" if x["score"] > 0 else "S"
            parts.append("%s:%s e=%.4f z=%.2f r=%.0f" % (x["symbol"], tag, x["edge"], x["z"], x["rsi"]))
        print("[CORE] c=%d opens=%d | %s" % (self.cycle_n, self.open_count, " | ".join(parts)), flush=True)

        n_top = max(1, len(scanned) // 5)
        for a in scanned[:n_top]:
            side, reason = self.decide(a)
            print("[CORE] DECIDE %s score=%.3f z=%.2f rsi=%.1f edge=%.5f → %s | %s" % (
                a["symbol"], a["score"], a["z"], a["rsi"], a["edge"], side or "SKIP", reason
            ), flush=True)
            if side:
                self.enter(a, side, reason)


if __name__ == "__main__":
    print("[CORE] LIVE v3 START lev=%d-%d MIN_EDGE=%.4f NOTIONAL=%.0f" % (MIN_LEV, MAX_LEV, MIN_EDGE, NOTIONAL), flush=True)
    core = LiveAcademicCore()
    try:
        while True:
            core.cycle()
            time.sleep(SCAN_SEC)
    except KeyboardInterrupt:
        print("[CORE] stop opens=%d" % core.open_count, flush=True)
        sys.exit(0)
