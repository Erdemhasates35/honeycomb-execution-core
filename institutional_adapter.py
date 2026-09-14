#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compatibility adapter that upgrades legacy engine decisions without renaming them."""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

import alpha_core
from institutional_finance import directional_expected_move_bps, dynamic_exit_surface, net_edge_bps
from profit_economics import market_economics


def _f(x: Any, d: float = 0.0) -> float:
    try:
        import math
        v=float(x)
        return v if math.isfinite(v) else d
    except (TypeError,ValueError):
        return d


def normalize_decision(symbol: str, kernel=None, equity: float = 0.0,
                       open_positions=None) -> Optional[Dict[str, Any]]:
    d=alpha_core.get_technical_decision(symbol,equity=equity,open_positions=open_positions or [])
    if not d or not d.get("allow") or not d.get("side"):
        return d
    side=str(d["side"]).upper();confidence=_f(d.get("confidence"));atr_pct=max(0.0,_f(d.get("atr_pct")))
    # Legacy score is signed. Convert it into a signed price forecast and keep
    # direction intact instead of treating positive/negative moves identically.
    score=_f(d.get("score"));model_move_pct=(score/100.0)*max(atr_pct,0.01)*2.2
    expected_bps=directional_expected_move_bps(model_move_pct,confidence,atr_pct,side)
    spread_bps=0.0;funding_bps=0.0;econ={}
    if kernel is not None:
        try:
            econ=market_economics(kernel,symbol,side,horizon_hours=float(os.getenv("EXPECTED_HOLD_HOURS","1")))
            spread_bps=_f(econ.get("spread_bps"));funding_bps=_f(econ.get("funding_bps"))
        except Exception:
            return {**d,"allow":False,"reason":"economics_unavailable"}
    maker=_f(econ.get("maker_fee"),_f(os.getenv("MAKER_FEE_RATE","0.0002"),.0002));taker=_f(econ.get("taker_fee"),_f(os.getenv("TAKER_FEE_RATE",os.getenv("FEE_RATE","0.0005")),.0005));slip=_f(os.getenv("EXECUTION_SLIPPAGE_BPS","2"),2)
    edge=net_edge_bps(expected_bps,maker,taker,spread_bps,slip,funding_bps,"TAKER")
    if edge<_f(os.getenv("MIN_NET_EDGE_BPS","3"),3):
        return {**d,"allow":False,"reason":"net_edge_below_threshold","expected_move_bps":expected_bps,"net_edge_bps":edge}
    regime=str(d.get("regime") or "RANGE")
    regime_mult={"TREND_UP":1.9,"TREND_DOWN":1.9,"HIGHVOL":2.2,"RANGE":1.3,"DEATH":0.8}.get(regime,1.5)
    ex=dynamic_exit_surface(side,max(_f(d.get("entry"),0.0),1.0),max(atr_pct,.20),confidence,regime_mult,.8)
    return {**d,"expected_move_bps":expected_bps,"net_edge_bps":edge,"spread_bps":spread_bps,"funding_bps":funding_bps,
            "margin_fraction":min(.05,max(0.0,_f(os.getenv("PROFIT_MARGIN_FRACTION","0.05"),.05))),
            "tp_pct":ex["tp_pct"],"sl_pct":ex["sl_pct"],"exit_surface":ex}
