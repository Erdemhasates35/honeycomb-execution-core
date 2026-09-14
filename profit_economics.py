#!/data/data/com.termux/files/usr/bin/python3
# -*- coding: utf-8 -*-
"""Profit-first execution economics using signed expected return and live costs."""
from __future__ import annotations

import math
import os
import time
from typing import Any, Dict

from institutional_finance import funding_cost_fraction, net_edge_bps as _net_edge_bps

MIN_LEVERAGE = max(1, int(float(os.getenv("MIN_LEVERAGE", os.getenv("LEV_MIN", "40")))))
MAX_LEVERAGE = max(MIN_LEVERAGE, int(float(os.getenv("MAX_LEVERAGE", "75"))))
DEFAULT_TAKER = max(0.0, float(os.getenv("TAKER_FEE_RATE", os.getenv("FEE_RATE", "0.0005"))))
DEFAULT_MAKER = max(0.0, float(os.getenv("MAKER_FEE_RATE", "0.0002")))
SLIPPAGE_BPS = max(0.0, float(os.getenv("EXECUTION_SLIPPAGE_BPS", os.getenv("SCANNER_SLIPPAGE_BPS", "2.0"))))
COMMISSION_CACHE_TTL = max(1.0, float(os.getenv("COMMISSION_CACHE_TTL_SEC", "300")))
_commission_cache: Dict[tuple[str, str], tuple[float, float, float]] = {}


def finite(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
        return v if math.isfinite(v) else default
    except (TypeError, ValueError):
        return default


def leverage_floor(requested: Any, maximum: int | None = None) -> int:
    lo = max(1, MIN_LEVERAGE)
    hi = min(MAX_LEVERAGE, max(1, int(maximum))) if maximum is not None else MAX_LEVERAGE
    lo = min(lo, hi)
    return max(lo, min(hi, int(round(finite(requested, lo)))))


def _commission_rates(kernel, symbol: str) -> tuple[float, float]:
    key = (str(getattr(kernel, "venue", "usdt")), symbol.upper())
    now = time.time()
    cached = _commission_cache.get(key)
    if cached and now - cached[2] < COMMISSION_CACHE_TTL:
        return cached[0], cached[1]
    try:
        path = "/fapi/v1/commissionRate" if getattr(kernel, "venue", "usdt") == "usdt" else "/dapi/v1/commissionRate"
        data = kernel._http("GET", path, {"symbol": symbol}, signed=True, weight=20)
        maker = max(0.0, finite(data.get("makerCommissionRate"), DEFAULT_MAKER))
        taker = max(0.0, finite(data.get("takerCommissionRate"), DEFAULT_TAKER))
        _commission_cache[key] = (maker, taker, now)
        return maker, taker
    except Exception:
        return (cached[0], cached[1]) if cached else (DEFAULT_MAKER, DEFAULT_TAKER)


def market_economics(kernel, symbol: str, side: str, horizon_hours: float = 1.0) -> Dict[str, float]:
    bid, ask, mid = kernel.book(symbol)
    spread_bps = max(0.0, (ask - bid) / max(mid, 1e-12) * 10000.0)
    maker, taker = _commission_rates(kernel, symbol)
    funding, next_ms = 0.0, 0.0
    try:
        premium = kernel._http("GET", kernel.v["premium"], {"symbol": symbol}, signed=False, weight=1)
        funding = finite(premium.get("lastFundingRate"), 0.0)
        next_ms = finite(premium.get("nextFundingTime"), 0.0)
    except Exception:
        pass
    now_ms = time.time() * 1000.0
    horizon_sec = max(0.0, finite(horizon_hours)) * 3600.0
    next_sec = max(0.0, (next_ms - now_ms) / 1000.0) if next_ms > now_ms else 0.0
    # When the next settlement has already passed relative to now, the next
    # interval is the first possible settlement in the horizon.
    if next_ms > now_ms:
        next_from_now = (next_ms - now_ms) / 1000.0
    else:
        next_from_now = 0.0
    fund_signed = funding_cost_fraction(funding, side, horizon_sec, next_from_now)
    fund_bps = fund_signed * 10000.0
    # Maker orders do not cross the spread by definition; adverse selection is
    # represented separately when the caller has a measurable estimate.
    maker_roundtrip = 2.0 * maker
    taker_roundtrip = 2.0 * taker + spread_bps / 10000.0 + SLIPPAGE_BPS / 10000.0
    return {
        "maker_fee": maker, "taker_fee": taker, "spread_bps": spread_bps,
        "funding_rate": funding, "next_funding_seconds": next_sec,
        "funding_cost": max(0.0, fund_signed), "funding_credit": max(0.0, -fund_signed),
        "funding_signed": fund_signed, "funding_bps": fund_bps,
        "maker_roundtrip_cost": maker_roundtrip, "taker_roundtrip_cost": taker_roundtrip,
        "entry_mid": mid, "bid": bid, "ask": ask,
    }


def net_edge(expected_move_pct: float, econ: Dict[str, float], style: str = "TAKER") -> float:
    """Expected signed net return fraction; positive means economically favorable."""
    expected_bps = finite(expected_move_pct) * 100.0
    edge_bps = _net_edge_bps(
        expected_bps, econ.get("maker_fee", DEFAULT_MAKER), econ.get("taker_fee", DEFAULT_TAKER),
        econ.get("spread_bps", 0.0) if style.upper() != "MAKER" else 0.0,
        SLIPPAGE_BPS if style.upper() != "MAKER" else 0.0,
        econ.get("funding_bps", 0.0), style,
    )
    return edge_bps / 10000.0


def choose_leverage(confidence: float, edge_pct: float) -> int:
    q = max(0.0, min(1.0, finite(confidence) / 100.0))
    e = max(0.0, min(1.0, finite(edge_pct) / 1.5))
    score = 0.60 * q + 0.40 * e
    return leverage_floor(round(MIN_LEVERAGE + (MAX_LEVERAGE - MIN_LEVERAGE) * score ** 1.20))


def choose_style(econ: Dict[str, float], expected_move_pct: float, maker_fill_probability: float = 0.55) -> str:
    p = max(0.0, min(1.0, finite(maker_fill_probability, 0.55)))
    maker = net_edge(expected_move_pct, econ, "MAKER")
    taker = net_edge(expected_move_pct, econ, "TAKER")
    maker_ev = p * maker
    return "MAKER" if maker_ev > taker and maker_ev > 0 else "TAKER"


def sizing(balance: float, risk_fraction: float, leverage: int, max_notional: float, min_notional: float = 5.0) -> Dict[str, float]:
    bal = max(0.0, finite(balance)); lev = leverage_floor(leverage)
    margin = max(0.0, bal * max(0.0, finite(risk_fraction)))
    notional = min(max(0.0, finite(max_notional)), margin * lev)
    return {"balance": bal, "margin": margin, "notional": notional, "leverage": float(lev),
            "tradable": 1.0 if notional >= min_notional else 0.0}
