#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared adaptive profit runtime.

Pure decision/accounting helpers; it does not place orders by itself. The
objective is expected net edge after execution costs, with exchange limits and
portfolio risk remaining hard constraints.
"""
from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from institutional_finance import (
    dynamic_exit_surface,
    net_edge_bps as _net_edge_bps,
    position_size_from_risk,
)


def finite(value: Any, default: float = 0.0) -> float:
    try:
        x = float(value)
        return x if math.isfinite(x) else default
    except (TypeError, ValueError):
        return default


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, finite(x, lo)))


@dataclass
class RuntimeConfig:
    margin_fraction: float = 0.05
    min_leverage: int = 40
    max_leverage: int = 75
    min_net_edge_bps: float = 3.0
    maker_fee_rate: float = 0.0002
    taker_fee_rate: float = 0.0005
    slippage_bps: float = 2.0

    @classmethod
    def from_env(cls) -> "RuntimeConfig":
        lo = max(1, int(float(os.getenv("MIN_LEVERAGE", os.getenv("LEV_MIN", "40")))))
        hi = max(lo, int(float(os.getenv("MAX_LEVERAGE", "75"))))
        return cls(
            margin_fraction=clamp(float(os.getenv("MARGIN_PCT", os.getenv("PROFIT_MARGIN_FRACTION", "0.05"))), 0.0, 1.0),
            min_leverage=lo,
            max_leverage=hi,
            min_net_edge_bps=max(0.0, finite(os.getenv("MIN_NET_EDGE_BPS", "3.0"), 3.0)),
            maker_fee_rate=max(0.0, finite(os.getenv("MAKER_FEE_RATE", "0.0002"), 0.0002)),
            taker_fee_rate=max(0.0, finite(os.getenv("TAKER_FEE_RATE", "0.0005"), 0.0005)),
            slippage_bps=max(0.0, finite(os.getenv("EXECUTION_SLIPPAGE_BPS", "2.0"), 2.0)),
        )


def dynamic_leverage(confidence: float, atr_pct: float, spread_bps: float,
                     available_leverage: Optional[float] = None,
                     cfg: Optional[RuntimeConfig] = None) -> int:
    """Confidence/volatility/liquidity adaptive leverage, bounded by exchange max."""
    cfg = cfg or RuntimeConfig.from_env()
    exchange_hi = int(finite(available_leverage, cfg.max_leverage)) if available_leverage else cfg.max_leverage
    hi = min(cfg.max_leverage, max(1, exchange_hi))
    lo = min(cfg.min_leverage, hi)
    c = clamp(confidence / 100.0, 0.0, 1.0)
    vol = clamp(atr_pct / 2.0, 0.0, 1.0)
    liq = clamp(spread_bps / 10.0, 0.0, 1.0)
    score = clamp(0.70 * c + 0.20 * (1.0 - vol) + 0.10 * (1.0 - liq), 0.0, 1.0)
    return int(round(lo + score * (hi - lo)))


def net_edge_bps(expected_move_bps: float, maker: bool = False,
                 spread_bps: float = 0.0, slippage_bps: Optional[float] = None,
                 funding_bps: float = 0.0, cfg: Optional[RuntimeConfig] = None,
                 market_impact_bps: float = 0.0,
                 adverse_selection_bps: float = 0.0) -> float:
    cfg = cfg or RuntimeConfig.from_env()
    slip = cfg.slippage_bps if slippage_bps is None else max(0.0, finite(slippage_bps))
    return _net_edge_bps(
        expected_move_bps,
        cfg.maker_fee_rate,
        cfg.taker_fee_rate,
        spread_bps,
        slip,
        funding_bps,
        "MAKER" if maker else "TAKER",
        market_impact_bps,
        adverse_selection_bps,
    )


def choose_execution(expected_move_bps: float, spread_bps: float,
                     funding_bps: float = 0.0,
                     maker_fill_probability: float = 0.55,
                     cfg: Optional[RuntimeConfig] = None) -> Dict[str, Any]:
    """Compare maker expected value against taker immediacy."""
    cfg = cfg or RuntimeConfig.from_env()
    p = clamp(maker_fill_probability, 0.0, 1.0)
    maker = net_edge_bps(expected_move_bps, True, spread_bps, 0.0, funding_bps, cfg)
    taker = net_edge_bps(expected_move_bps, False, spread_bps, cfg.slippage_bps, funding_bps, cfg)
    maker_ev = p * maker
    style = "MAKER" if maker_ev >= taker and maker_ev >= cfg.min_net_edge_bps else ("TAKER" if taker >= cfg.min_net_edge_bps else "PASS")
    return {"style": style, "maker_net_bps": maker, "taker_net_bps": taker,
            "maker_ev_bps": maker_ev, "selected_net_bps": max(maker_ev, taker),
            "threshold_bps": cfg.min_net_edge_bps}


def margin_notional(equity: float, price: float, leverage: float,
                    cfg: Optional[RuntimeConfig] = None) -> Dict[str, float]:
    cfg = cfg or RuntimeConfig.from_env()
    return position_size_from_risk(equity, cfg.margin_fraction, 0.0, leverage, float("inf"), price)


def adaptive_exits(side: str, entry: float, atr_pct: float, confidence: float,
                   regime_multiplier: float = 1.5, trailing_fraction: float = 0.8) -> Dict[str, float]:
    return dynamic_exit_surface(side, entry, atr_pct, confidence, regime_multiplier, trailing_fraction)


class PnLTracker:
    """Incremental realized/unrealized PnL with fee, funding, MAE and MFE."""
    def __init__(self) -> None:
        self.open: Dict[str, Dict[str, float]] = {}
        self.realized = 0.0
        self.fees = 0.0
        self.funding = 0.0

    def open_trade(self, trade_id: str, side: str, entry: float, qty: float, margin: float = 0.0) -> None:
        self.open[str(trade_id)] = {"side": 1.0 if str(side).upper() == "LONG" else -1.0,
                                    "entry": finite(entry), "qty": abs(finite(qty)),
                                    "margin": max(0.0, finite(margin)), "mfe": 0.0,
                                    "mae": 0.0, "opened": time.time()}

    def mark(self, trade_id: str, price: float) -> Optional[Dict[str, float]]:
        p = self.open.get(str(trade_id))
        if not p:
            return None
        raw = p["side"] * (finite(price) - p["entry"]) * p["qty"]
        p["mfe"] = max(p["mfe"], raw)
        p["mae"] = min(p["mae"], raw)
        margin = p.get("margin", 0.0)
        return {"unrealized": raw, "unrealized_pct_margin": raw / margin * 100.0 if margin > 0 else 0.0,
                "mfe": p["mfe"], "mae": p["mae"], "age_sec": max(0.0, time.time() - p["opened"])}

    def close(self, trade_id: str, price: float, fee: float = 0.0, funding: float = 0.0) -> Optional[Dict[str, float]]:
        p = self.open.pop(str(trade_id), None)
        if not p:
            return None
        gross = p["side"] * (finite(price) - p["entry"]) * p["qty"]
        fee_v = max(0.0, finite(fee))
        funding_v = finite(funding)
        self.fees += fee_v
        self.funding += funding_v
        net = gross - fee_v - funding_v
        self.realized += net
        margin = p.get("margin", 0.0)
        return {"gross": gross, "fee": fee_v, "funding": funding_v, "net": net,
                "net_pct_margin": net / margin * 100.0 if margin > 0 else 0.0,
                "mfe": p["mfe"], "mae": p["mae"],
                "hold_sec": max(0.0, time.time() - p["opened"])}

    def snapshot(self) -> Dict[str, float]:
        return {"realized_net": self.realized, "fees": self.fees, "funding": self.funding,
                "open_positions": float(len(self.open))}
