#!/data/data/com.termux/files/usr/bin/python3
# -*- coding: utf-8 -*-
"""Compatibility runner for the existing LOBSTER engine.

Keeps the original engine intact and raises its leverage floor to 40x while
preserving its 10-agent, 30+ indicator and microstructure implementation.
"""
from __future__ import annotations


# =====================================================================
# MAXIMUM PROFIT LAYER (Academic — Shared)
# Moreira & Muir (2017) Volatility Targeting
# López de Prado Triple Barrier Method
# Wilder ATR Adaptive Trailing (1978)
# Thorp Fractional Kelly (1969)
# Moskowitz, Ooi, Pedersen Time-Series Momentum (2012)
# =====================================================================

def dynamic_tp_sl_maxprofit(atr_pct, score, regime="RANGE", confidence=70.0):
    """Dinamik TP/SL — sadece net kâr maksimizasyonu."""
    atr_pct = max(0.12, min(5.0, float(atr_pct or 0.7)))
    quality = max(0.0, min(1.0, (float(score) - 50.0) / 40.0)) if score > 5 else max(0.0, min(1.0, float(score)))
    conf = max(0.0, min(1.0, float(confidence) / 100.0))
    regime = str(regime).upper()
    if regime in ("TREND", "TREND_UP", "TREND_DOWN"):
        tp_mult = 2.7 + 2.3 * quality * conf
        sl_mult = 0.68 + 0.38 * (1.0 - quality)
    else:
        tp_mult = 1.85 + 1.65 * quality
        sl_mult = 0.88 + 0.48 * (1.0 - quality)
    tp = max(0.65, min(8.5, atr_pct * tp_mult))
    sl = max(0.28, min(2.9, atr_pct * sl_mult))
    return round(tp, 4), round(sl, 4)

def adaptive_trail_maxprofit(mfe_pct, atr_pct, stage=0):
    """MFE büyüdükçe stop'u agresif sıkılaştır."""
    mfe = max(0.0, float(mfe_pct or 0.0))
    atr_pct = max(0.12, float(atr_pct or 0.7))
    if mfe < atr_pct * 0.60:
        return 0.0
    base = atr_pct * (0.15 if stage <= 0 else 0.29 if stage == 1 else 0.46)
    lock = base + mfe * 0.24
    return round(min(mfe * 0.78, lock), 4)

def cost_aware_net_edge(raw_edge_or_score, atr_pct, fee=0.0004, slip_bps=2.0):
    """Fee + slippage sonrası net edge. Negatifse işlem açma."""
    gross = abs(float(raw_edge_or_score or 0.0))
    if gross > 5:  # score tarzı
        gross = (gross / 100.0) * (float(atr_pct or 0.7) / 100.0) * 2.5
    cost = float(fee) * 2.0 + (float(slip_bps) / 10000.0)
    return gross - cost

def volatility_size_boost(atr_pct, confidence=70.0, base_risk=0.08):
    """Düşük vol → daha büyük pozisyon (Moreira-Muir)."""
    atr_pct = max(0.15, float(atr_pct or 0.8))
    scale = 0.88 / atr_pct
    scale = max(0.50, min(1.75, scale))
    if confidence and float(confidence) > 78:
        scale *= 1.10
    return round(min(0.12, float(base_risk) * scale), 4)

def regime_tp_boost(regime, score):
    """Trend rejimlerinde TP mesafesini artır."""
    if str(regime).upper() in ("TREND", "TREND_UP", "TREND_DOWN"):
        return 1.0 + 0.38 * max(0.0, min(1.0, (float(score) - 50) / 40.0))
    return 1.0

import os, threading
import lobster_extreme_momentum_engine as base

base.MIN_LEV = max(40, int(float(os.getenv("MIN_LEVERAGE", "40"))))
base.MAX_LEV = max(base.MIN_LEV, int(float(os.getenv("MAX_LEVERAGE", "75"))))

if __name__ == "__main__":
    base.main()
