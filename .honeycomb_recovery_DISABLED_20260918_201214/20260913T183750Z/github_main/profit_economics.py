#!/data/data/com.termux/files/usr/bin/python3
# -*- coding: utf-8 -*-
"""Profit-first execution economics.

No synthetic data and no mock fills. Uses live Binance Futures data when a
LiveKernel is supplied. The objective is expected net return after commission,
spread/slippage and funding, with a configurable leverage floor of 40x.
"""
from __future__ import annotations

import math
import os
import time
from typing import Any, Dict

MIN_LEVERAGE = int(float(os.getenv("MIN_LEVERAGE", os.getenv("LEV_MIN", "40"))))
MAX_LEVERAGE = int(float(os.getenv("MAX_LEVERAGE", "75")))
DEFAULT_TAKER = float(os.getenv("TAKER_FEE_RATE", os.getenv("FEE_RATE", "0.0005")))
DEFAULT_MAKER = float(os.getenv("MAKER_FEE_RATE", "0.0002"))
SLIPPAGE_BPS = float(os.getenv("EXECUTION_SLIPPAGE_BPS", os.getenv("SCANNER_SLIPPAGE_BPS", "2.0")))
COMMISSION_CACHE_TTL = float(os.getenv("COMMISSION_CACHE_TTL_SEC", "300"))
_commission_cache: Dict[tuple[str, str], tuple[float, float, float]] = {}


def finite(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
        return v if math.isfinite(v) else default
    except Exception:
        return default


def leverage_floor(requested: Any, maximum: int | None = None) -> int:
    lo = max(1, MIN_LEVERAGE)
    hi = max(lo, int(maximum if maximum is not None else MAX_LEVERAGE))
    return max(lo, min(hi, int(round(finite(requested, lo)))))


def _commission_rates(kernel, symbol: str) -> tuple[float, float]:
    """Return live (maker,taker) rates when Binance provides them."""
    key = (str(getattr(kernel, "venue", "usdt")), symbol.upper())
    now = time.time()
    cached = _commission_cache.get(key)
    if cached and now - cached[2] < COMMISSION_CACHE_TTL:
        return cached[0], cached[1]
    try:
        path = "/fapi/v1/commissionRate" if getattr(kernel, "venue", "usdt") == "usdt" else "/dapi/v1/commissionRate"
        data = kernel._http("GET", path, {"symbol": symbol}, signed=True, weight=20)
        maker = finite(data.get("makerCommissionRate"), DEFAULT_MAKER)
        taker = finite(data.get("takerCommissionRate"), DEFAULT_TAKER)
        _commission_cache[key] = (maker, taker, now)
        return maker, taker
    except Exception:
        return (cached[0], cached[1]) if cached else (DEFAULT_MAKER, DEFAULT_TAKER)


def market_economics(kernel, symbol: str, side: str, horizon_hours: float = 1.0) -> Dict[str, float]:
    bid, ask, mid = kernel.book(symbol)
    spread_bps = max(0.0, (ask - bid) / max(mid, 1e-12) * 10000.0)
    maker, taker = _commission_rates(kernel, symbol)
    try:
        premium = kernel._http("GET", kernel.v["premium"], {"symbol": symbol}, signed=False, weight=1)
        funding = finite(premium.get("lastFundingRate"), 0.0)
        next_ms = finite(premium.get("nextFundingTime"), 0.0)
    except Exception:
        funding, next_ms = 0.0, 0.0
    funding_cost = 0.0
    funding_credit = 0.0
    if next_ms > time.time() * 1000:
        hours = max(0.0, (next_ms - time.time() * 1000) / 3600000.0)
        if hours <= max(0.0, horizon_hours):
            # Positive funding is paid by longs and received by shorts.
            signed = funding if str(side).upper() == "LONG" else -funding
            funding_cost = max(0.0, signed)
            funding_credit = max(0.0, -signed)
    spread_cost = spread_bps / 10000.0
    slip_cost = SLIPPAGE_BPS / 10000.0
    maker_roundtrip = 2.0 * maker + spread_cost
    taker_roundtrip = 2.0 * taker + spread_cost + slip_cost
    return {
        "maker_fee": maker,
        "taker_fee": taker,
        "spread_bps": spread_bps,
        "funding_rate": funding,
        "funding_cost": funding_cost,
        "funding_credit": funding_credit,
        "maker_roundtrip_cost": maker_roundtrip,
        "taker_roundtrip_cost": taker_roundtrip,
        "entry_mid": mid,
        "bid": bid,
        "ask": ask,
    }


def net_edge(expected_move_pct: float, econ: Dict[str, float], style: str = "TAKER") -> float:
    """Expected net return fraction after execution cost and funding."""
    gross = abs(finite(expected_move_pct)) / 100.0
    cost = econ["maker_roundtrip_cost"] if style.upper() == "MAKER" else econ["taker_roundtrip_cost"]
    return gross - cost - max(0.0, econ.get("funding_cost", 0.0)) + max(0.0, econ.get("funding_credit", 0.0))


def choose_leverage(confidence: float, edge_pct: float) -> int:
    q = max(0.0, min(1.0, finite(confidence) / 100.0))
    e = max(0.0, min(1.0, finite(edge_pct) / 1.5))
    score = 0.60 * q + 0.40 * e
    return leverage_floor(round(MIN_LEVERAGE + (MAX_LEVERAGE - MIN_LEVERAGE) * score ** 1.20))


def choose_style(econ: Dict[str, float], expected_move_pct: float, maker_fill_probability: float = 0.55) -> str:
    """Select maker when its expected net value beats taker after fill probability."""
    p = max(0.0, min(1.0, finite(maker_fill_probability, 0.55)))
    maker = net_edge(expected_move_pct, econ, "MAKER")
    taker = net_edge(expected_move_pct, econ, "TAKER")
    # A maker order that does not fill has an opportunity cost; compare expected value.
    maker_ev = p * maker
    return "MAKER" if maker_ev > taker else "TAKER"


def sizing(balance: float, risk_fraction: float, leverage: int, max_notional: float, min_notional: float = 5.0) -> Dict[str, float]:
    bal = max(0.0, finite(balance))
    lev = leverage_floor(leverage)
    margin = max(0.0, bal * max(0.0, finite(risk_fraction)))
    notional = min(max(0.0, finite(max_notional)), margin * lev)
    return {
        "balance": bal,
        "margin": margin,
        "notional": notional,
        "leverage": float(lev),
        "tradable": 1.0 if notional >= min_notional else 0.0,
    }
