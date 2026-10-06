#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
α-Agent 03 — Kelly Dynamic Sizing
Academic: Edward O. Thorp (1969) + fractional Kelly + Moreira & Muir vol targeting
"""
from __future__ import annotations
import os
from typing import Dict, Any

KELLY_FRACTION = float(os.getenv("KELLY_FRACTION", "0.25"))
MAX_KELLY_CAP = float(os.getenv("MAX_KELLY_CAP", "0.22"))
MIN_RISK_PCT = float(os.getenv("SCANNER_MIN_RISK", "0.004"))
MAX_RISK_PCT = float(os.getenv("SCANNER_MAX_RISK", "0.025"))
BASE_RISK_PCT = float(os.getenv("SCANNER_RISK", "0.015"))
TARGET_VOL = float(os.getenv("TARGET_VOL", "0.12"))

def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))

def kelly_fraction(win_rate: float, avg_win: float, avg_loss: float,
                   fraction: float = KELLY_FRACTION) -> float:
    wr = clamp(win_rate, 0.01, 0.99)
    aw = max(avg_win, 1e-9)
    al = max(avg_loss, 1e-9)
    b = aw / al
    q = 1.0 - wr
    full = (b * wr - q) / b
    return clamp(full * fraction, 0.0, MAX_KELLY_CAP)

def volatility_target_size(atr_pct: float, target_vol: float = TARGET_VOL,
                           base_risk: float = BASE_RISK_PCT) -> float:
    vol = max(atr_pct / 100.0, 0.005)
    scale = target_vol / vol
    return clamp(base_risk * scale, MIN_RISK_PCT, MAX_RISK_PCT)

def compute_size(equity: float, atr_pct: float, win_rate: float,
                 avg_win: float, avg_loss: float, quality: float,
                 open_notional: float = 0.0, max_notional: float = 500.0,
                 portfolio_multiplier: float = 2.5) -> Dict[str, Any]:
    k = kelly_fraction(win_rate, avg_win, avg_loss)
    vol_size = volatility_target_size(atr_pct)
    q_mult = 0.85 + (quality / 100.0) * 0.30
    risk_pct = clamp(vol_size * (0.6 + k * 2.8) * q_mult, MIN_RISK_PCT, MAX_RISK_PCT)
    lev = int(10 + (40 * (quality / 100.0)))
    lev = clamp(lev, 10, 50)
    notional = equity * risk_pct * lev
    max_allowed = equity * portfolio_multiplier
    if open_notional + notional > max_allowed or notional > max_notional:
        notional = max(0.0, min(max_notional, max_allowed - open_notional))
        risk_pct = notional / max(equity * lev, 1e-9)
    return {"risk_pct": round(risk_pct, 6), "leverage": lev,
            "notional": round(notional, 2), "kelly_raw": round(k, 5),
            "vol_size": round(vol_size, 6), "q_mult": round(q_mult, 4)}

if __name__ == "__main__":
    k = kelly_fraction(0.58, 18.0, 9.0)
    assert 0.0 < k <= MAX_KELLY_CAP
    size = compute_size(12845.0, 0.11, 0.58, 18.0, 9.0, 84.0)
    assert size["notional"] > 0
    print("PASS", size)
