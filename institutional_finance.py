#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Institutional-grade shared trading economics.

Pure deterministic helpers for signal direction, expected move, execution cost,
funding settlements, margin-return PnL, risk sizing and adaptive exits.
No market data, orders or synthetic fills are created here.
"""
from __future__ import annotations

import math
from typing import Any, Dict


def finite(value: Any, default: float = 0.0) -> float:
    try:
        x = float(value)
        return x if math.isfinite(x) else default
    except (TypeError, ValueError):
        return default


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, finite(value, lo)))


def directional_expected_move_bps(model_move_pct: float, confidence: float, atr_pct: float, side: str) -> float:
    """Return signed expected price move in bps, oriented to the trade side.

    model_move_pct is the model's signed price forecast. A SHORT reverses the
    forecast because a negative underlying move is profitable for the short.
    Confidence scales conviction; ATR supplies a conservative minimum scale.
    """
    raw = finite(model_move_pct)
    conf = clamp(confidence / 100.0, 0.0, 1.0)
    vol_floor = max(0.0, finite(atr_pct)) * 0.05
    magnitude = raw * max(conf, vol_floor)
    if str(side).upper() == "SHORT":
        magnitude = -magnitude
    return magnitude * 100.0


def funding_cost_fraction(funding_rate: float, side: str, holding_seconds: float,
                          next_funding_seconds: float, interval_seconds: float = 8 * 3600) -> float:
    """Return signed funding transfer as a fraction of notional.

    Positive result is a cost; negative result is a credit. Only funding
    settlements actually crossed by the holding horizon are counted.
    """
    horizon = max(0.0, finite(holding_seconds))
    next_t = max(0.0, finite(next_funding_seconds))
    interval = max(1.0, finite(interval_seconds, 8 * 3600))
    if horizon < next_t:
        return 0.0
    settlements = 1 + int((horizon - next_t) // interval)
    rate = finite(funding_rate)
    signed = rate if str(side).upper() == "LONG" else -rate
    return signed * settlements


def net_edge_bps(expected_move_bps: float, maker_fee_rate: float, taker_fee_rate: float,
                 spread_bps: float, slippage_bps: float, funding_bps: float,
                 style: str = "TAKER", market_impact_bps: float = 0.0,
                 adverse_selection_bps: float = 0.0) -> float:
    """Expected signed price move after full round-trip economic costs."""
    fee_rate = finite(maker_fee_rate if str(style).upper() == "MAKER" else taker_fee_rate)
    spread = max(0.0, finite(spread_bps))
    slip = max(0.0, finite(slippage_bps))
    impact = max(0.0, finite(market_impact_bps))
    adverse = max(0.0, finite(adverse_selection_bps))
    # Crossing a quoted spread is a round-trip economic cost; commissions are
    # charged on entry and exit. Maker orders retain a small adverse-selection
    # allowance supplied by the caller instead of pretending fills are free.
    execution_cost = 2.0 * fee_rate * 10000.0 + spread + slip + impact + adverse
    return finite(expected_move_bps) - execution_cost - finite(funding_bps)


def pnl_percent(side: str, entry: float, exit: float, quantity: float,
                margin: float, fee_rate: float = 0.0, funding: float = 0.0) -> float:
    """Net realized PnL as percentage of posted margin, not price change."""
    e = finite(entry)
    x = finite(exit)
    q = abs(finite(quantity))
    m = finite(margin)
    if e <= 0 or x <= 0 or q <= 0 or m <= 0:
        return 0.0
    direction = 1.0 if str(side).upper() == "LONG" else -1.0
    gross = direction * (x - e) * q
    notional_entry = e * q
    commission = notional_entry * max(0.0, finite(fee_rate))
    net = gross - commission + finite(funding)
    return net / m * 100.0


def position_size_from_risk(equity: float, risk_fraction: float, stop_distance_pct: float,
                             leverage: float, max_notional: float, price: float) -> Dict[str, float]:
    """Size from a 5% margin budget while exposing stop-risk separately.

    Margin budget is equity*risk_fraction. Notional is margin*leverage and is
    capped by max_notional. The returned risk_at_stop is the price-loss amount
    at the requested stop distance before fees/funding.
    """
    eq = max(0.0, finite(equity))
    frac = clamp(risk_fraction, 0.0, 1.0)
    lev = max(1.0, finite(leverage, 1.0))
    px = max(0.0, finite(price))
    margin = eq * frac
    notional = min(max(0.0, finite(max_notional)), margin * lev)
    qty = notional / px if px > 0 else 0.0
    stop = max(0.0, finite(stop_distance_pct)) / 100.0
    return {
        "equity": eq,
        "margin": margin,
        "notional": notional,
        "quantity": qty,
        "leverage": lev,
        "risk_at_stop": notional * stop,
        "risk_at_stop_pct_equity": (notional * stop / eq * 100.0) if eq > 0 else 0.0,
    }


def dynamic_exit_surface(side: str, entry: float, atr_pct: float, confidence: float,
                         regime_multiplier: float = 1.5, trailing_fraction: float = 0.8) -> Dict[str, float]:
    """Construct TP/SL/trailing distances from volatility and conviction."""
    e = max(0.0, finite(entry))
    atr = max(0.0, finite(atr_pct))
    conf = clamp(confidence / 100.0, 0.0, 1.0)
    regime = clamp(regime_multiplier, 0.75, 3.0)
    trail = clamp(trailing_fraction, 0.25, 1.5)
    tp_pct = clamp(atr * (1.2 + 1.3 * conf) * regime, 0.20, 8.0)
    sl_pct = clamp(atr * (0.85 + 0.55 * (1.0 - conf)) * max(0.85, regime * 0.85), 0.15, 4.0)
    trail_pct = clamp(atr * trail, 0.10, 4.0)
    if str(side).upper() == "SHORT":
        return {"tp": e * (1.0 - tp_pct / 100.0), "sl": e * (1.0 + sl_pct / 100.0), "trail_pct": trail_pct,
                "tp_pct": tp_pct, "sl_pct": sl_pct}
    return {"tp": e * (1.0 + tp_pct / 100.0), "sl": e * (1.0 - sl_pct / 100.0), "trail_pct": trail_pct,
            "tp_pct": tp_pct, "sl_pct": sl_pct}
