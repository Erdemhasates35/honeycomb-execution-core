#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Canonical Honeycomb trading mathematics.

All values are signed in trade direction. Critical inputs reject NaN/inf rather
than silently converting missing market data to zero.
"""
from __future__ import annotations
import math
from typing import Any, Dict, Iterable, Sequence

def finite(value: Any, name: str = "value") -> float:
    try: x=float(value)
    except (TypeError,ValueError): raise ValueError("%s is not numeric"%name)
    if not math.isfinite(x): raise ValueError("%s is non-finite"%name)
    return x

def clamp(x: Any, lo: float, hi: float, name: str="value") -> float:
    return max(lo,min(hi,finite(x,name)))

def expected_move_bps(model_move_pct: float, confidence: float, atr_pct: float) -> float:
    move=finite(model_move_pct,"model_move_pct"); conf=clamp(confidence,0,100,"confidence")/100
    vol=max(0.0,finite(atr_pct,"atr_pct"))
    return move*100.0*max(conf, min(1.0, vol/2.0))

def funding_cost_fraction(funding_rate: float, side: str, holding_seconds: float,
                          next_funding_seconds: float, interval_seconds: float=8*3600) -> float:
    r=finite(funding_rate,"funding_rate"); h=max(0.0,finite(holding_seconds,"holding_seconds"))
    nxt=max(0.0,finite(next_funding_seconds,"next_funding_seconds")); interval=max(1.0,finite(interval_seconds,"interval_seconds"))
    if h < nxt: return 0.0
    settlements=1+int((h-nxt)//interval)
    signed=r if side.upper()=="LONG" else -r
    return signed*settlements

def net_edge_bps(expected_bps: float, maker_fee: float, taker_fee: float,
                 spread_bps: float, slippage_bps: float, funding_bps: float,
                 style: str="TAKER", impact_bps: float=0.0, adverse_bps: float=0.0) -> float:
    e=finite(expected_bps,"expected_bps")
    fee=maker_fee if style.upper()=="MAKER" else taker_fee
    cost=2*finite(fee,"fee")*10000 + max(0,finite(spread_bps,"spread_bps")) + max(0,finite(slippage_bps,"slippage_bps")) + max(0,finite(impact_bps,"impact_bps")) + max(0,finite(adverse_bps,"adverse_bps"))
    return e-cost-finite(funding_bps,"funding_bps")

def kelly_fraction(win_probability: float, reward_risk: float, fraction: float=0.25) -> float:
    p=clamp(win_probability,0,1,"win_probability"); b=max(1e-9,finite(reward_risk,"reward_risk"))
    full=p-(1-p)/b
    return clamp(full*clamp(fraction,0,1,"fraction"),0,1,"kelly")

def kelly_from_expectancy(expected_return: float, variance: float, fraction: float=0.25) -> float:
    mu=finite(expected_return,"expected_return"); var=max(1e-12,finite(variance,"variance"))
    return clamp((mu/var)*clamp(fraction,0,1,"fraction"),0,1,"kelly")

def position_size_from_risk(equity: float, margin_fraction: float, leverage: float,
                            max_notional: float, price: float, stop_distance_pct: float) -> Dict[str,float]:
    eq=max(0.0,finite(equity,"equity")); mf=clamp(margin_fraction,0,1,"margin_fraction")
    lev=max(1.0,finite(leverage,"leverage")); cap=max(0.0,finite(max_notional,"max_notional")); px=finite(price,"price")
    margin=eq*mf; notional=min(cap,margin*lev); stop=max(0.0,finite(stop_distance_pct,"stop_distance_pct"))/100
    qty=notional/px
    risk=notional*stop
    return {"equity":eq,"margin":margin,"notional":notional,"quantity":qty,"leverage":lev,
            "risk_at_stop":risk,"risk_at_stop_pct_equity":risk/eq if eq else math.inf}

def dynamic_exit_surface(side: str, entry: float, atr_pct: float, quality: float,
                         regime_multiplier: float=1.0) -> Dict[str,float]:
    e=finite(entry,"entry"); a=max(0.01,finite(atr_pct,"atr_pct")); q=clamp(quality,0,1,"quality")
    rm=clamp(regime_multiplier,0.75,2.5,"regime_multiplier")
    sl=clamp(a*(0.85+0.55*(1-q))*rm,0.15,4.0)
    tp=clamp(a*(1.35+2.2*q)*rm,0.25,8.0)
    trail=clamp(a*(0.35+0.35*q),0.10,4.0)
    if side.upper()=="SHORT":
        return {"tp":e*(1-tp/100),"sl":e*(1+sl/100),"tp_pct":tp,"sl_pct":sl,"trail_pct":trail}
    return {"tp":e*(1+tp/100),"sl":e*(1-sl/100),"tp_pct":tp,"sl_pct":sl,"trail_pct":trail}

def pnl_percent(side: str, entry: float, exit: float, quantity: float, margin: float,
                entry_fee_rate: float=0.0, funding: float=0.0, exit_fee_rate: float|None=None) -> float:
    e=finite(entry,"entry"); x=finite(exit,"exit"); q=abs(finite(quantity,"quantity")); m=finite(margin,"margin")
    if min(e,x,q,m)<=0: raise ValueError("invalid pnl inputs")
    sign=1 if side.upper()=="LONG" else -1
    gross=(x-e)*q*sign
    ex=entry_fee_rate if exit_fee_rate is None else exit_fee_rate
    fees=e*q*max(0,finite(entry_fee_rate,"entry_fee_rate")) + x*q*max(0,finite(ex,"exit_fee_rate"))
    return (gross-fees+finite(funding,"funding"))/m*100
