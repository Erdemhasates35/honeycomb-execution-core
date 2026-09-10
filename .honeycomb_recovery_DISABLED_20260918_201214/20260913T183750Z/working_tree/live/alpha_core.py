#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
α-Core Production Module
Academic foundations:
- Kelly Criterion (Thorp 1969 / Edward Thorp)
- Volatility Targeting (Moreira & Muir 2017)
- Time-Series Momentum (Moskowitz, Ooi, Pedersen 2012)
- Mean-Reversion Confluence (Bollinger + RSI + Williams literature)
- Cost-Aware Expected Value (transaction cost literature)
- Adaptive ATR Trailing (Wilder 1978 + modern extensions)
- Optimal Partial Scaling (optimal stopping / scale-out research)
"""
from __future__ import annotations
import math
import os
import time
from typing import Any, Dict, List, Optional, Tuple
from statistics import median

# ========================= IMPORTS =========================
try:
    from live.kernel import (
        klines, ema, rsi, atr, macd, adx, bollinger_pctb,
        stochastic, williams_r, mfi, cci, _finite_num, _gt, _lt, _ge, _le
    )
except Exception:
    # fallback pure implementations already present in kernel
    pass

# ========================= CONFIG =========================
TF_WEIGHTS = [
    ("1m", 0.07), ("3m", 0.07), ("5m", 0.17), ("15m", 0.20),
    ("30m", 0.15), ("1h", 0.14), ("2h", 0.10), ("4h", 0.10)
]

REVERSION_THRESHOLD = float(os.getenv("REVERSION_THRESHOLD", "66"))
OMEGA_ENTRY_SCORE   = float(os.getenv("OMEGA_ENTRY_SCORE", "74"))
OMEGA_STRONG_SCORE  = float(os.getenv("OMEGA_STRONG_SCORE", "84"))
BASE_RISK_PCT       = float(os.getenv("SCANNER_RISK", "0.015"))
MIN_RISK_PCT        = float(os.getenv("SCANNER_MIN_RISK", "0.004"))
MAX_RISK_PCT        = float(os.getenv("SCANNER_MAX_RISK", "0.025"))
LEV_MIN             = int(float(os.getenv("LEV_MIN", "10")))
LEV_MAX             = int(float(os.getenv("MAX_LEVERAGE", "50")))
MAX_NOTIONAL        = float(os.getenv("MAX_POSITION_SIZE_USDT", "500"))
PORTFOLIO_MULTIPLIER = float(os.getenv("SCANNER_PORTFOLIO_MULTIPLIER", "2.5"))
FEE_RATE            = float(os.getenv("FEE_RATE", "0.0004"))
SLIPPAGE_BPS        = float(os.getenv("SCANNER_SLIPPAGE_BPS", "2.0"))
FUNDING_RESERVE_PCT = float(os.getenv("SCANNER_FUNDING_RESERVE", "0.0002"))
RSI_LOW             = float(os.getenv("SCANNER_RSI_LOW", "25"))
RSI_HIGH            = float(os.getenv("SCANNER_RSI_HIGH", "75"))
BAND_EXTREME        = float(os.getenv("SCANNER_BAND_EXTREME", "0.97"))
MAX_SPREAD_BPS      = float(os.getenv("SCANNER_MAX_SPREAD_BPS", "12"))

# ========================= UTILS =========================
def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))

def finite(x: Any, default: float = 0.0) -> float:
    return _finite_num(x, default)

# ========================= 1. KELLY FRACTION (Thorp) =========================
def kelly_fraction(win_rate: float, avg_win: float, avg_loss: float, fraction: float = 0.35) -> float:
    """
    Half-Kelly / fractional Kelly for aggressive yet controlled growth.
    Academic: Edward O. Thorp – The Kelly Criterion in Blackjack, Sports Betting, and the Stock Market.
    """
    wr = clamp(finite(win_rate), 0.01, 0.99)
    aw = max(finite(avg_win), 1e-9)
    al = max(finite(avg_loss), 1e-9)
    b = aw / al
    q = 1.0 - wr
    full = (b * wr - q) / b
    return clamp(full * fraction, 0.0, 0.25)  # hard cap 25%

# ========================= 2. VOLATILITY TARGETING (Moreira & Muir) =========================
def volatility_target_size(atr_pct: float, target_vol: float = 0.12, base_risk: float = BASE_RISK_PCT) -> float:
    """
    Scale position inverse to realized volatility.
    Academic: Moreira & Muir (2017) – Volatility-Managed Portfolios.
    """
    vol = max(finite(atr_pct) / 100.0, 0.005)
    scale = target_vol / vol
    return clamp(base_risk * scale, MIN_RISK_PCT, MAX_RISK_PCT)

# ========================= 3. COST-AWARE EXPECTED VALUE =========================
def cost_aware_ev(score: float, quality: float, atr_pct: float, side: str,
                  fee: float = FEE_RATE, slip_bps: float = SLIPPAGE_BPS,
                  funding: float = FUNDING_RESERVE_PCT) -> float:
    """
    Net EV after fees + slippage + funding reserve.
    Academic basis: transaction-cost-adjusted alpha literature.
    """
    gross = (abs(score) / 100.0) * (quality / 100.0) * (atr_pct / 100.0) * 2.8
    cost = fee * 2 + (slip_bps / 10000.0) + funding
    return gross - cost

# ========================= 4. ADAPTIVE TRAILING MULTIPLIER =========================
def adaptive_trailing_multiplier(atr_pct: float, mfe_pct: float, regime: str) -> float:
    """
    Dynamic trailing distance based on ATR + MFE + regime.
    Rooted in Wilder ATR + modern adaptive stop research.
    """
    base = 1.6
    if regime in ("TREND_UP", "TREND_DOWN"):
        base = 2.1
    elif regime == "HIGHVOL":
        base = 2.8
    mfe_boost = clamp(finite(mfe_pct) / 1.5, 0.0, 1.2)
    return clamp(base + mfe_boost - (finite(atr_pct) * 0.15), 1.1, 3.8)

# ========================= 5. PARTIAL SCALE-OUT PLAN =========================
def partial_scale_plan(quality: float, atr_pct: float) -> List[Tuple[float, float]]:
    """
    Optimal scale-out levels (academic optimal stopping / scaling literature).
    Returns list of (profit_pct, close_fraction)
    """
    if quality >= OMEGA_STRONG_SCORE:
        return [(0.35, 0.30), (0.70, 0.30), (1.20, 0.25)]
    if quality >= OMEGA_ENTRY_SCORE:
        return [(0.40, 0.35), (0.85, 0.35)]
    return [(0.55, 0.50)]

# ========================= 6. NOTIONAL BAND CHECK =========================
def notional_band_check(notional: float, equity: float, open_notional: float) -> bool:
    """
    Maximum addressable notional bands with portfolio multiplier.
    Prevents over-concentration while allowing aggressive size when equity grows.
    """
    if equity <= 0:
        return False
    max_allowed = equity * PORTFOLIO_MULTIPLIER
    return (open_notional + notional) <= max_allowed and notional <= MAX_NOTIONAL

# ========================= 7. LIQUIDITY FILTER =========================
def liquidity_filter(spread_bps: float, vol_ratio: float, atr_pct: float) -> bool:
    """
    Strict liquidity gate: low spread + sufficient volume + non-death ATR.
    """
    return (finite(spread_bps) <= MAX_SPREAD_BPS and
            finite(vol_ratio) >= 0.65 and
            0.04 <= finite(atr_pct) <= 0.55)

# ========================= 8. REGIME KILL SWITCH =========================
def regime_kill_switch(regime: str, atr_pct: float) -> bool:
    """Hard kill for DEATH / extreme HIGHVOL."""
    if regime == "DEATH":
        return True
    if regime == "HIGHVOL" and atr_pct > 0.32:
        return True
    return False

# ========================= INDICATOR SET =========================
def full_indicator_set(symbol: str, interval: str = "5m") -> Dict[str, float]:
    d = klines(symbol, interval, 80)
    if not d or len(d["c"]) < 40:
        return {}
    c, h, l, v = d["c"], d["h"], d["l"], d["v"]
    e9 = ema(c, 9)
    e21 = ema(c, 21)
    r = rsi(c, 14)
    a = atr(h, l, c, 14)
    st = stochastic(h, l, c, 14)
    will = williams_r(h, l, c, 14)
    mf = mfi(h, l, c, v, 14)
    cc = cci(h, l, c, 20)
    pctb = bollinger_pctb(c, 20)
    adx_v = adx(h, l, c, 14)
    mom = (c[-1] - c[-9]) / c[-9] * 100 if len(c) >= 9 else 0.0
    vol_ratio = v[-1] / (sum(v[-20:]) / 20 + 1e-9) if len(v) >= 20 else 1.0

    out = {
        "ema_fast": e9, "ema_slow": e21, "rsi": r, "atr": a,
        "atr_pct": (a / c[-1] * 100) if a and c[-1] else 0.0,
        "stoch": st[0] if st else 50.0,
        "williams_r": will, "mfi": mf, "cci": cc,
        "bb_position": pctb if pctb is not None else 0.5,
        "adx": adx_v, "mom": mom, "vol_ratio": vol_ratio,
        "close": c[-1]
    }
    return {k: round(finite(v), 5) for k, v in out.items() if v is not None}

# ========================= REGIME =========================
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

# ========================= SCORE TF + MULTI HORIZON =========================
def score_tf(symbol: str, interval: str) -> Tuple[float, Dict]:
    d = klines(symbol, interval, 80)
    if not d or len(d["c"]) < 40:
        return 0.0, {}
    c, h, l, v = d["c"], d["h"], d["l"], d["v"]
    e9, e21 = ema(c, 9), ema(c, 21)
    r = rsi(c, 14)
    a = atr(h, l, c, 14)
    mom = (c[-1] - c[-9]) / c[-9] * 100 if len(c) >= 9 else 0.0
    m_line, m_sig, m_hist = macd(c)
    adx_v = adx(h, l, c, 14)
    pctb = bollinger_pctb(c, 20)
    if None in (e9, e21, r, a):
        return 0.0, {}
    vol_ratio = v[-1] / (sum(v[-20:]) / 20 + 1e-9)
    s = 0.0
    if e9 > e21: s += 16
    else: s -= 16
    if r > 58: s += 7
    elif r < 42: s -= 7
    if mom > 0.25: s += 9
    elif mom < -0.25: s -= 9
    if vol_ratio > 1.2: s += 6
    elif vol_ratio < 0.7: s -= 5
    if m_hist is not None:
        s += 8 if m_hist > 0 else -8
    if adx_v is not None and adx_v > 25:
        s *= 1.15
    if pctb is not None:
        if pctb > 0.95: s -= 5
        elif pctb < 0.05: s += 5
    return s, {
        "atr_pct": a / c[-1] * 100,
        "rsi": r, "mom": mom, "vol": vol_ratio, "adx": adx_v
    }

def multi_horizon(symbol: str) -> Tuple[float, Dict]:
    total, details = 0.0, {}
    for tf, w in TF_WEIGHTS:
        sc, det = score_tf(symbol, tf)
        total += sc * w
        if det:
            details[tf] = det
    return round(total, 4), details

# ========================= EXTREME QUALITY =========================
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
    if x["rsi"] <= RSI_LOW: long_votes += 1
    elif x["rsi"] >= RSI_HIGH: short_votes += 1
    if x["stoch"] <= 20: long_votes += 1
    elif x["stoch"] >= 80: short_votes += 1
    if x["williams"] <= -80: long_votes += 1
    elif x["williams"] >= -20: short_votes += 1
    if x["cci"] <= -100: long_votes += 1
    elif x["cci"] >= 100: short_votes += 1
    if x["mfi"] <= 20: long_votes += 1
    elif x["mfi"] >= 80: short_votes += 1
    if x["bb_position"] <= 0.05: long_votes += 1
    elif x["bb_position"] >= 0.95: short_votes += 1
    long_s = long_votes / 6.0 * 100.0
    short_s = short_votes / 6.0 * 100.0
    return long_s, short_s, {
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
        aligned = (direction > 0 and x["ema_fast"] > x["ema_slow"]) or \
                  (direction < 0 and x["ema_fast"] < x["ema_slow"])
        adx_mult = 1.12 if aligned else 0.92

    quality = (oscillator_score * 0.38 + band_score * 0.27 +
               rsi_score * 0.22 + ema_confirmation * 0.13) * adx_mult
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

# ========================= RISK MULTIPLIER =========================
_expectancy_state = {"wins": 0, "losses": 0, "sum_win": 0.0, "sum_loss": 0.0, "last": 0.0}

def _update_expectancy_and_risk(last_pnl: float) -> None:
    global _expectancy_state
    if last_pnl > 0:
        _expectancy_state["wins"] += 1
        _expectancy_state["sum_win"] += last_pnl
    else:
        _expectancy_state["losses"] += 1
        _expectancy_state["sum_loss"] += abs(last_pnl)
    _expectancy_state["last"] = last_pnl

def get_risk_multiplier() -> float:
    w = _expectancy_state["wins"]
    l = _expectancy_state["losses"]
    total = w + l
    if total < 8:
        return 1.0
    wr = w / total
    avg_w = _expectancy_state["sum_win"] / max(w, 1)
    avg_l = _expectancy_state["sum_loss"] / max(l, 1)
    k = kelly_fraction(wr, avg_w, avg_l)
    return clamp(0.55 + k * 3.2, 0.35, 1.85)

def on_trade_closed(symbol: str, side: str, net_pnl: float, confidence: float, regime: str) -> None:
    _update_expectancy_and_risk(net_pnl)

# ========================= CORRELATION =========================
def correlation_blocked(symbol: str, side: str, open_positions: List[Tuple[str, str]]) -> bool:
    if len(open_positions) >= 8:
        return True
    same_side = sum(1 for s, sd in open_positions if sd == side)
    if same_side >= 5:
        return True
    # simple cluster block (BTC/ETH heavy)
    heavy = {"BTCUSDT", "ETHUSDT"}
    if symbol in heavy and any(s in heavy for s, _ in open_positions):
        return True
    return False

# ========================= ENTRY GATE (Ana Kar Kapısı) =========================
def evaluate_entry_gate(symbol: str, equity: float, open_notional: float,
                        spread_bps: float = 0.0) -> Optional[Dict[str, Any]]:
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

    risk_m = get_risk_multiplier()
    risk_pct = volatility_target_size(atr_pct, base_risk=BASE_RISK_PCT * risk_m)
    risk_pct = clamp(risk_pct, MIN_RISK_PCT, MAX_RISK_PCT)

    lev = int(LEV_MIN + (LEV_MAX - LEV_MIN) * (eq["quality"] / 100.0))
    lev = clamp(lev, LEV_MIN, LEV_MAX)

    notional = equity * risk_pct * lev
    if not notional_band_check(notional, equity, open_notional):
        return None

    ev = cost_aware_ev(mh_score, eq["quality"], atr_pct, side)
    if ev < 0.0012:  # minimum net edge
        return None

    return {
        "symbol": symbol,
        "side": side,
        "regime": regime,
        "atr_pct": round(atr_pct, 4),
        "score": round(mh_score, 4),
        "quality": eq["quality"],
        "risk_pct": round(risk_pct, 5),
        "leverage": lev,
        "notional": round(notional, 2),
        "ev": round(ev, 5),
        "scale_plan": partial_scale_plan(eq["quality"], atr_pct),
        "trail_mult": adaptive_trailing_multiplier(atr_pct, 0.0, regime),
        "details": {"mh": mh_det, "eq": eq},
    }
