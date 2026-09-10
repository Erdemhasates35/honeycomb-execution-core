#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
alpha_core.py — Honeycomb technical decision core.

Self-contained (own klines + indicators) so parliament/scanner never crash
with "klines is not defined" or circular live.__init__ imports.

Academic stack (max-profit / min-cost):
  1. Kelly Criterion (Thorp 1969)
  2. Volatility targeting (Moreira & Muir 2017, JFE)
  3. Time-series momentum (Moskowitz, Ooi, Pedersen 2012)
  4. Cost-aware EV (transaction-cost alpha literature)
  5. Wilder ATR adaptive trailing (1978)
  6. Triple-barrier style TP/SL (López de Prado)
  7. Liquidity/spread filter (Amihud 2002 analogue)
  8. Regime kill-switch (low-vol death / high-vol explosion)
  9. Correlation / concentration shield
 10. Expectancy-based risk multiplier (anti-martingale)
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import sys
import time
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE_TTL = float(os.getenv("ALPHA_KLINE_TTL", "12"))
BASE_URL = os.getenv("BINANCE_BASE_URL", "https://fapi.binance.com")

DEFENSE_ENABLED = os.getenv("DEFENSE_ENABLED", "1") != "0"
REVERSION_THRESHOLD = float(os.getenv("REVERSION_THRESHOLD", "66"))
OMEGA_ENTRY_SCORE = float(os.getenv("OMEGA_ENTRY_SCORE", "74"))
OMEGA_STRONG_SCORE = float(os.getenv("OMEGA_STRONG_SCORE", "84"))
BASE_RISK_PCT = float(os.getenv("SCANNER_RISK", "0.015"))
MIN_RISK_PCT = float(os.getenv("SCANNER_MIN_RISK", "0.004"))
MAX_RISK_PCT = float(os.getenv("SCANNER_MAX_RISK", "0.025"))
LEV_MIN = int(float(os.getenv("LEV_MIN", "10")))
LEV_MAX = int(float(os.getenv("MAX_LEVERAGE", "50")))
MAX_NOTIONAL = float(os.getenv("MAX_POSITION_SIZE_USDT", "500"))
PORTFOLIO_MULTIPLIER = float(os.getenv("SCANNER_PORTFOLIO_MULTIPLIER", "2.5"))
FEE_RATE = float(os.getenv("FEE_RATE", "0.0004"))
SLIPPAGE_BPS = float(os.getenv("SCANNER_SLIPPAGE_BPS", "2.0"))
FUNDING_RESERVE_PCT = float(os.getenv("SCANNER_FUNDING_RESERVE", "0.0002"))
RSI_LOW = float(os.getenv("SCANNER_RSI_LOW", "25"))
RSI_HIGH = float(os.getenv("SCANNER_RSI_HIGH", "75"))
MAX_SPREAD_BPS = float(os.getenv("SCANNER_MAX_SPREAD_BPS", "12"))
MIN_FINAL_CONF = float(os.getenv("MIN_FINAL_CONF", "57"))

TF_WEIGHTS = [
    ("1m", 0.07), ("3m", 0.07), ("5m", 0.17), ("15m", 0.20),
    ("30m", 0.15), ("1h", 0.14), ("2h", 0.10), ("4h", 0.10),
]

_kmem: Dict[str, Tuple[float, Dict[str, List[float]]]] = {}
_expectancy_state = {"wins": 0, "losses": 0, "sum_win": 0.0, "sum_loss": 0.0, "last": 0.0, "defense": 0.0}


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def finite(x: Any, default: float = 0.0) -> float:
    try:
        if x is None:
            return default
        v = float(x)
        return v if math.isfinite(v) else default
    except (TypeError, ValueError):
        return default


def ensure_db(path: str) -> str:
    """Create parent dir; fall back to /tmp if unwritable (fixes sqlite OperationalError)."""
    path = os.path.abspath(path)
    d = os.path.dirname(path) or "."
    try:
        os.makedirs(d, exist_ok=True)
        open(path, "a").close()
        return path
    except Exception:
        alt = os.path.join("/tmp", os.path.basename(path) or "honeycomb_alpha.db")
        try:
            open(alt, "a").close()
            return alt
        except Exception:
            return path


# -------------------- klines (dict) — THE crash that Termux showed --------------------
def klines(symbol: str, interval: str = "5m", limit: int = 80) -> Optional[Dict[str, List[float]]]:
    key = "%s_%s_%d" % (symbol, interval, int(limit))
    now = time.time()
    hit = _kmem.get(key)
    if hit and now - hit[0] < CACHE_TTL:
        return hit[1]
    url = "%s/fapi/v1/klines?symbol=%s&interval=%s&limit=%d" % (
        BASE_URL.rstrip("/"), symbol, interval, int(limit)
    )
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "honeycomb-alpha-core/omega", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=8) as r:
            raw = json.loads(r.read().decode("utf-8"))
        if not raw:
            return None
        data = {
            "o": [float(x[1]) for x in raw],
            "h": [float(x[2]) for x in raw],
            "l": [float(x[3]) for x in raw],
            "c": [float(x[4]) for x in raw],
            "v": [float(x[5]) for x in raw],
        }
        _kmem[key] = (now, data)
        return data
    except Exception:
        return hit[1] if hit else None


def ema(arr, p):
    if not arr or len(arr) < p:
        return None
    k = 2.0 / (p + 1)
    v = sum(arr[:p]) / p
    for x in arr[p:]:
        v = x * k + v * (1 - k)
    return v


def rsi(arr, p=14):
    if not arr or len(arr) < p + 1:
        return None
    g, l = [], []
    for i in range(1, len(arr)):
        d = arr[i] - arr[i - 1]
        g.append(max(d, 0.0))
        l.append(max(-d, 0.0))
    ag = sum(g[-p:]) / p
    al = sum(l[-p:]) / p
    if al == 0:
        return 100.0
    return 100.0 - (100.0 / (1.0 + ag / al))


def atr(h, l, c, p=14):
    if not c or len(c) < p + 1:
        return None
    trs = []
    for i in range(1, len(c)):
        trs.append(max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])))
    return sum(trs[-p:]) / p


def momentum(c, p=10):
    if not c or len(c) < p + 1 or c[-p - 1] == 0:
        return 0.0
    return (c[-1] - c[-p - 1]) / c[-p - 1] * 100.0


def macd(closes, fast=12, slow=26, signal=9):
    if not closes or len(closes) < slow + signal:
        return None, None, None
    e_fast = ema(closes, fast)
    e_slow = ema(closes, slow)
    if e_fast is None or e_slow is None:
        return None, None, None
    line = e_fast - e_slow
    return line, None, line


def bollinger_pctb(closes, period=20):
    if not closes or len(closes) < period:
        return None
    w = closes[-period:]
    mid = sum(w) / period
    var = sum((x - mid) ** 2 for x in w) / period
    sd = math.sqrt(max(var, 0.0))
    up, lo = mid + 2 * sd, mid - 2 * sd
    if up == lo:
        return 0.5
    return (closes[-1] - lo) / (up - lo)


def stochastic(h, l, c, p=14):
    if min(len(h), len(l), len(c)) < p:
        return 50.0
    hh, ll = max(h[-p:]), min(l[-p:])
    if hh == ll:
        return 50.0
    return (c[-1] - ll) / (hh - ll) * 100.0


def williams_r(h, l, c, p=14):
    if min(len(h), len(l), len(c)) < p:
        return -50.0
    hh, ll = max(h[-p:]), min(l[-p:])
    if hh == ll:
        return -50.0
    return (hh - c[-1]) / (hh - ll) * -100.0


def mfi(h, l, c, v, p=14):
    n = min(len(h), len(l), len(c), len(v))
    if n < p + 1:
        return 50.0
    pos = neg = 0.0
    for i in range(n - p, n):
        tp = (h[i] + l[i] + c[i]) / 3.0
        prev = (h[i - 1] + l[i - 1] + c[i - 1]) / 3.0
        raw = tp * v[i]
        if tp > prev:
            pos += raw
        elif tp < prev:
            neg += raw
    if neg == 0:
        return 100.0
    return 100.0 - (100.0 / (1.0 + pos / neg))


def cci(h, l, c, p=20):
    n = min(len(h), len(l), len(c))
    if n < p:
        return 0.0
    tp = [(h[i] + l[i] + c[i]) / 3.0 for i in range(n)]
    w = tp[-p:]
    avg = sum(w) / p
    md = sum(abs(x - avg) for x in w) / p
    if md == 0:
        return 0.0
    return (tp[-1] - avg) / (0.015 * md)


def adx(h, l, c, p=14):
    n = min(len(h), len(l), len(c))
    if n < p + 2:
        return 0.0
    plus_dm = minus_dm = trs = []
    plus_dm, minus_dm, trs = [], [], []
    for i in range(1, n):
        up = h[i] - h[i - 1]
        dn = l[i - 1] - l[i]
        plus_dm.append(up if up > dn and up > 0 else 0.0)
        minus_dm.append(dn if dn > up and dn > 0 else 0.0)
        trs.append(max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])))
    atr_v = sum(trs[-p:]) / p
    if atr_v <= 0:
        return 0.0
    pdi = 100.0 * (sum(plus_dm[-p:]) / p) / atr_v
    mdi = 100.0 * (sum(minus_dm[-p:]) / p) / atr_v
    den = pdi + mdi
    return 0.0 if den == 0 else abs(pdi - mdi) / den * 100.0


def full_indicator_set(symbol: str, interval: str = "5m") -> Dict[str, float]:
    d = klines(symbol, interval, 80)
    if not d or len(d["c"]) < 40:
        return {}
    c, h, l, v = d["c"], d["h"], d["l"], d["v"]
    e9, e21 = ema(c, 9), ema(c, 21)
    r = rsi(c, 14)
    a = atr(h, l, c, 14)
    st = stochastic(h, l, c, 14)
    will = williams_r(h, l, c, 14)
    mf = mfi(h, l, c, v, 14)
    cc = cci(h, l, c, 20)
    pctb = bollinger_pctb(c, 20)
    adx_v = adx(h, l, c, 14)
    mom = momentum(c, 8)
    vol_ratio = v[-1] / (sum(v[-20:]) / 20 + 1e-9) if len(v) >= 20 else 1.0
    out = {
        "ema_fast": e9, "ema_slow": e21, "rsi": r, "atr": a,
        "atr_pct": (a / c[-1] * 100) if a and c[-1] else 0.0,
        "stoch": st, "williams_r": will, "mfi": mf, "cci": cc,
        "bb_position": pctb if pctb is not None else 0.5,
        "adx": adx_v, "mom": mom, "vol_ratio": vol_ratio, "close": c[-1],
    }
    return {k: round(finite(val), 5) for k, val in out.items() if val is not None}


def detect_regime(symbol: str) -> Tuple[str, float]:
    d5 = klines(symbol, "5m", 60)
    d15 = klines(symbol, "15m", 40)
    if not d5 or not d15:
        return "UNKNOWN", 0.1
    c5, h5, l5 = d5["c"], d5["h"], d5["l"]
    c15 = d15["c"]
    a = atr(h5, l5, c5, 14)
    atr_pct = (a / c5[-1] * 100) if a and c5[-1] > 0 else 0.1
    e9, e21 = ema(c5, 9), ema(c5, 21)
    e55 = ema(c15, 21) if len(c15) > 25 else None
    slope = (e9 - e21) / c5[-1] * 100 if e9 and e21 else 0.0
    if atr_pct < 0.035:
        return "DEATH", atr_pct
    if atr_pct > 0.18:
        return "HIGHVOL", atr_pct
    if e9 and e21 and e55:
        if e9 > e21 > e55 and slope > 0.08:
            return "TREND_UP", atr_pct
        if e9 < e21 < e55 and slope < -0.08:
            return "TREND_DOWN", atr_pct
    return "RANGE", atr_pct


def score_tf(symbol: str, interval: str) -> Tuple[float, Dict]:
    d = klines(symbol, interval, 80)
    if not d or len(d["c"]) < 40:
        return 0.0, {}
    c, h, l, v = d["c"], d["h"], d["l"], d["v"]
    e9, e21 = ema(c, 9), ema(c, 21)
    r = rsi(c, 14)
    a = atr(h, l, c, 14)
    mom = momentum(c, 8)
    m_line, _s, m_hist = macd(c)
    adx_v = adx(h, l, c, 14)
    pctb = bollinger_pctb(c, 20)
    if None in (e9, e21, r, a):
        return 0.0, {}
    vol_ratio = v[-1] / (sum(v[-20:]) / 20 + 1e-9)
    s = 0.0
    if e9 > e21:
        s += 16
    else:
        s -= 16
    if r > 58:
        s += 7
    elif r < 42:
        s -= 7
    if mom > 0.25:
        s += 9
    elif mom < -0.25:
        s -= 9
    if vol_ratio > 1.2:
        s += 6
    elif vol_ratio < 0.7:
        s -= 5
    if m_hist is not None:
        s += 8 if m_hist > 0 else -8
    if adx_v is not None and adx_v > 25:
        s *= 1.15
    if pctb is not None:
        if pctb > 0.95:
            s -= 5
        elif pctb < 0.05:
            s += 5
    return s, {
        "atr_pct": a / c[-1] * 100,
        "rsi": r, "mom": mom, "vol": vol_ratio, "adx": adx_v,
    }


def multi_horizon(symbol: str) -> Tuple[float, Dict]:
    total, details = 0.0, {}
    for tf, w in TF_WEIGHTS:
        sc, det = score_tf(symbol, tf)
        total += sc * w
        if det:
            details[tf] = det
    return round(total, 4), details


def kelly_fraction(win_rate: float, avg_win: float, avg_loss: float, fraction: float = 0.35) -> float:
    wr = clamp(finite(win_rate), 0.01, 0.99)
    aw = max(finite(avg_win), 1e-9)
    al = max(finite(avg_loss), 1e-9)
    b = aw / al
    q = 1.0 - wr
    full = (b * wr - q) / b
    return clamp(full * fraction, 0.0, 0.25)


def volatility_target_size(atr_pct: float, target_vol: float = 0.12, base_risk: float = BASE_RISK_PCT) -> float:
    vol = max(finite(atr_pct) / 100.0, 0.005)
    scale = target_vol / vol
    return clamp(base_risk * scale, MIN_RISK_PCT, MAX_RISK_PCT)


def cost_aware_ev(score: float, quality: float, atr_pct: float, fee: float = FEE_RATE,
                  slip_bps: float = SLIPPAGE_BPS, funding: float = FUNDING_RESERVE_PCT) -> float:
    gross = (abs(score) / 100.0) * (quality / 100.0) * (atr_pct / 100.0) * 2.8
    cost = fee * 2 + (slip_bps / 10000.0) + funding
    return gross - cost


def adaptive_trailing_multiplier(atr_pct: float, mfe_pct: float, regime: str) -> float:
    base = 1.6
    if regime in ("TREND_UP", "TREND_DOWN"):
        base = 2.1
    elif regime == "HIGHVOL":
        base = 2.8
    mfe_boost = clamp(finite(mfe_pct) / 1.5, 0.0, 1.2)
    return clamp(base + mfe_boost - (finite(atr_pct) * 0.15), 1.1, 3.8)


def partial_scale_plan(quality: float, atr_pct: float) -> List[Tuple[float, float]]:
    if quality >= OMEGA_STRONG_SCORE:
        return [(0.35, 0.30), (0.70, 0.30), (1.20, 0.25)]
    if quality >= OMEGA_ENTRY_SCORE:
        return [(0.40, 0.35), (0.85, 0.35)]
    return [(0.55, 0.50)]


def notional_band_check(notional: float, equity: float, open_notional: float) -> bool:
    if equity <= 0:
        return False
    return (open_notional + notional) <= equity * PORTFOLIO_MULTIPLIER and notional <= MAX_NOTIONAL


def liquidity_filter(spread_bps: float, vol_ratio: float, atr_pct: float) -> bool:
    return (
        finite(spread_bps) <= MAX_SPREAD_BPS
        and finite(vol_ratio) >= 0.65
        and 0.04 <= finite(atr_pct) <= 0.55
    )


def regime_kill_switch(regime: str, atr_pct: float) -> bool:
    if not DEFENSE_ENABLED:
        return False
    if regime == "DEATH":
        return True
    if regime == "HIGHVOL" and atr_pct > 0.32:
        return True
    return False


def _arm_defense(level: float) -> None:
    _expectancy_state["defense"] = clamp(finite(level), 0.0, 1.0)


def _update_expectancy_and_risk(last_pnl: float) -> None:
    if last_pnl > 0:
        _expectancy_state["wins"] += 1
        _expectancy_state["sum_win"] += last_pnl
    else:
        _expectancy_state["losses"] += 1
        _expectancy_state["sum_loss"] += abs(last_pnl)
    _expectancy_state["last"] = last_pnl
    if last_pnl < 0:
        _arm_defense(min(1.0, _expectancy_state["defense"] + 0.15))
    else:
        _arm_defense(max(0.0, _expectancy_state["defense"] - 0.08))


def get_risk_multiplier() -> float:
    w = _expectancy_state["wins"]
    l = _expectancy_state["losses"]
    total = w + l
    defense = _expectancy_state["defense"]
    if total < 8:
        return clamp(1.0 - 0.5 * defense, 0.35, 1.85)
    wr = w / total
    avg_w = _expectancy_state["sum_win"] / max(w, 1)
    avg_l = _expectancy_state["sum_loss"] / max(l, 1)
    k = kelly_fraction(wr, avg_w, avg_l)
    return clamp(0.55 + k * 3.2 - 0.6 * defense, 0.35, 1.85)


def on_trade_closed(symbol: str, side: str, net_pnl: float, confidence: float, regime: str) -> None:
    _update_expectancy_and_risk(net_pnl)
    db = ensure_db(os.path.join(ROOT, "master_brain.db"))
    try:
        con = sqlite3.connect(db, timeout=8)
        con.execute(
            "CREATE TABLE IF NOT EXISTS trades(id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "ts INTEGER, symbol TEXT, side TEXT, net_pnl REAL, confidence REAL, regime TEXT)"
        )
        con.execute(
            "INSERT INTO trades(ts,symbol,side,net_pnl,confidence,regime) VALUES(?,?,?,?,?,?)",
            (int(time.time()), symbol, side, float(net_pnl), float(confidence), str(regime)),
        )
        con.commit()
        con.close()
    except Exception:
        pass


def correlation_blocked(symbol: str, side: str, open_positions: Optional[List[Tuple[str, str]]] = None) -> bool:
    open_positions = open_positions or []
    if len(open_positions) >= 8:
        return True
    same_side = sum(1 for _s, sd in open_positions if sd == side)
    if same_side >= 5:
        return True
    heavy = {"BTCUSDT", "ETHUSDT"}
    if symbol in heavy and any(s in heavy for s, _ in open_positions):
        return True
    return False


def normalize_indicator(ind: Dict[str, Any]) -> Dict[str, float]:
    return {
        "rsi": finite(ind.get("rsi"), 50),
        "stoch": finite(ind.get("stoch"), 50),
        "williams": finite(ind.get("williams_r"), -50),
        "cci": finite(ind.get("cci"), 0),
        "mfi": finite(ind.get("mfi"), 50),
        "bb_position": finite(ind.get("bb_position"), 0.5),
        "atr_pct": finite(ind.get("atr_pct"), 0),
        "adx": finite(ind.get("adx"), 0),
        "ema_fast": finite(ind.get("ema_fast"), 0),
        "ema_slow": finite(ind.get("ema_slow"), 0),
    }


def oscillator_components(x: Dict[str, float]) -> Tuple[float, float, Dict]:
    long_votes = short_votes = 0
    if x["rsi"] <= RSI_LOW:
        long_votes += 1
    elif x["rsi"] >= RSI_HIGH:
        short_votes += 1
    if x["stoch"] <= 20:
        long_votes += 1
    elif x["stoch"] >= 80:
        short_votes += 1
    if x["williams"] <= -80:
        long_votes += 1
    elif x["williams"] >= -20:
        short_votes += 1
    if x["cci"] <= -100:
        long_votes += 1
    elif x["cci"] >= 100:
        short_votes += 1
    if x["mfi"] <= 20:
        long_votes += 1
    elif x["mfi"] >= 80:
        short_votes += 1
    if x["bb_position"] <= 0.05:
        long_votes += 1
    elif x["bb_position"] >= 0.95:
        short_votes += 1
    return long_votes / 6.0 * 100.0, short_votes / 6.0 * 100.0, {
        "long_votes": float(long_votes), "short_votes": float(short_votes)
    }


def extreme_quality(indicators: Dict[str, Any], rev_score: float) -> Dict[str, Any]:
    x = normalize_indicator(indicators)
    long_o, short_o, osc = oscillator_components(x)
    direction = 1 if rev_score > 0 else -1
    oscillator_score = long_o if direction > 0 else short_o
    if direction > 0:
        band_score = clamp((0.50 - x["bb_position"]) * 200.0, 0, 100)
        rsi_score = clamp((50.0 - x["rsi"]) * 2.0, 0, 100)
    else:
        band_score = clamp((x["bb_position"] - 0.50) * 200.0, 0, 100)
        rsi_score = clamp((x["rsi"] - 50.0) * 2.0, 0, 100)
    if x["ema_fast"] and x["ema_slow"]:
        ema_gap = (x["ema_fast"] - x["ema_slow"]) / max(abs(x["ema_slow"]), 1e-12) * 100.0
        ema_confirmation = clamp((-ema_gap) * 15.0, 0, 100) if direction > 0 else clamp(ema_gap * 15.0, 0, 100)
    else:
        ema_confirmation = 0.0
    adx_mult = 1.0
    if x["adx"] > 25:
        aligned = (direction > 0 and x["ema_fast"] > x["ema_slow"]) or (
            direction < 0 and x["ema_fast"] < x["ema_slow"]
        )
        adx_mult = 1.12 if aligned else 0.92
    quality = (oscillator_score * 0.38 + band_score * 0.27 + rsi_score * 0.22 + ema_confirmation * 0.13) * adx_mult
    quality = clamp(quality, 0.0, 100.0)
    return {
        "quality": round(quality, 4),
        "direction": direction,
        "oscillator_score": round(oscillator_score, 4),
        "band_score": round(band_score, 4),
        "rsi_score": round(rsi_score, 4),
        "ema_confirmation": round(ema_confirmation, 4),
        "adx_mult": round(adx_mult, 4),
        "osc": osc,
        "atr_pct": x["atr_pct"],
        "adx": x["adx"],
    }


def evaluate_entry_gate(symbol: str, equity: float = 0.0, open_notional: float = 0.0,
                        spread_bps: float = 0.0, open_positions: Optional[List[Tuple[str, str]]] = None
                        ) -> Optional[Dict[str, Any]]:
    regime, atr_pct = detect_regime(symbol)
    if regime_kill_switch(regime, atr_pct):
        return None
    ind = full_indicator_set(symbol, "5m")
    if not ind:
        return None
    mh_score, mh_det = multi_horizon(symbol)
    eq = extreme_quality(ind, mh_score)
    if abs(mh_score) < REVERSION_THRESHOLD or eq["quality"] < OMEGA_ENTRY_SCORE:
        return None
    side = "LONG" if mh_score > 0 else "SHORT"
    if not liquidity_filter(spread_bps, ind.get("vol_ratio", 1.0), atr_pct):
        return None
    if correlation_blocked(symbol, side, open_positions or []):
        return None
    risk_m = get_risk_multiplier()
    risk_pct = volatility_target_size(atr_pct, base_risk=BASE_RISK_PCT * risk_m)
    lev = int(clamp(LEV_MIN + (LEV_MAX - LEV_MIN) * (eq["quality"] / 100.0), LEV_MIN, LEV_MAX))
    notional = max(equity, 0.0) * risk_pct * lev
    if equity > 0 and not notional_band_check(notional, equity, open_notional):
        return None
    ev = cost_aware_ev(mh_score, eq["quality"], atr_pct)
    if ev < 0.0012:
        return None
    return {
        "symbol": symbol, "side": side, "regime": regime,
        "atr_pct": round(atr_pct, 4), "score": round(mh_score, 4),
        "quality": eq["quality"], "risk_pct": round(risk_pct, 5),
        "leverage": lev, "notional": round(notional, 2), "ev": round(ev, 5),
        "confidence": round(eq["quality"], 1),
        "scale_plan": partial_scale_plan(eq["quality"], atr_pct),
        "trail_mult": adaptive_trailing_multiplier(atr_pct, 0.0, regime),
        "details": {"mh": mh_det, "eq": eq},
    }


def get_technical_decision(symbol: str, *args: Any, **kwargs: Any) -> Dict[str, Any]:
    """Parliament / Helix required surface. Never raises; always returns a dict."""
    open_positions = kwargs.get("open_positions") or []
    equity = finite(kwargs.get("equity") or kwargs.get("balance") or (args[0] if args else 0.0))
    try:
        regime, atr_pct = detect_regime(symbol)
        risk_m = get_risk_multiplier()
        if regime_kill_switch(regime, atr_pct):
            return {
                "allow": False, "side": None, "confidence": 0, "regime": regime,
                "risk_mult": 0.0, "score": 0.0, "atr_pct": atr_pct,
                "reason": "regime_kill",
            }
        gate = evaluate_entry_gate(symbol, equity=equity, open_positions=open_positions)
        if not gate:
            mh, _ = multi_horizon(symbol)
            side = "LONG" if mh > 0 else ("SHORT" if mh < 0 else None)
            conf = min(abs(mh), 99.0)
            allow = side is not None and conf >= (54 if regime == "RANGE" else MIN_FINAL_CONF)
            if allow and correlation_blocked(symbol, side, open_positions):
                return {
                    "allow": False, "side": None, "confidence": conf, "regime": regime,
                    "risk_mult": risk_m, "score": mh, "atr_pct": atr_pct,
                    "reason": "correlation",
                }
            return {
                "allow": allow, "side": side if allow else None, "confidence": conf,
                "regime": regime, "risk_mult": risk_m, "score": mh, "atr_pct": atr_pct,
                "reason": "mtf_fallback",
            }
        return {
            "allow": True, "side": gate["side"], "confidence": gate["confidence"],
            "regime": gate["regime"], "risk_mult": risk_m, "score": gate["score"],
            "atr_pct": gate["atr_pct"], "quality": gate["quality"],
            "risk_pct": gate["risk_pct"], "leverage": gate["leverage"],
            "ev": gate["ev"], "reason": "omega_gate",
        }
    except Exception as e:
        return {
            "allow": False, "side": None, "confidence": 0, "regime": "UNKNOWN",
            "risk_mult": 0.5, "score": 0.0, "atr_pct": 0.0, "reason": "error:%s" % e,
        }


# aliases used by older parliament copies
get_tech_decision = get_technical_decision
technical_decision = get_technical_decision
