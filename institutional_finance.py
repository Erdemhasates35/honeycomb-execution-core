#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Institutional-grade shared trading economics."""
from __future__ import annotations
import math
from typing import Any, Dict

def finite(value: Any, default: float = 0.0) -> float:
    try:
        x=float(value);return x if math.isfinite(x) else default
    except (TypeError,ValueError):return default

def clamp(value: float, lo: float, hi: float) -> float:return max(lo,min(hi,finite(value,lo)))

def directional_expected_move_bps(model_move_pct: float, confidence: float, atr_pct: float, side: str) -> float:
    """Signed expected price move in bps; caller supplies the forecast in trade direction."""
    raw=finite(model_move_pct);conf=clamp(confidence/100.0,0.0,1.0);vol_floor=max(0.0,finite(atr_pct))*0.05
    return raw*max(conf,vol_floor)*100.0

def funding_cost_fraction(funding_rate: float, side: str, holding_seconds: float, next_funding_seconds: float, interval_seconds: float=8*3600) -> float:
    horizon=max(0.0,finite(holding_seconds));next_t=max(0.0,finite(next_funding_seconds));interval=max(1.0,finite(interval_seconds,8*3600))
    if horizon<next_t:return 0.0
    settlements=1+int((horizon-next_t)//interval);rate=finite(funding_rate);signed=rate if str(side).upper()=="LONG" else -rate
    return signed*settlements

def net_edge_bps(expected_move_bps: float,maker_fee_rate: float,taker_fee_rate: float,spread_bps: float,slippage_bps: float,funding_bps: float,style: str="TAKER",market_impact_bps: float=0.0,adverse_selection_bps: float=0.0)->float:
    fee=finite(maker_fee_rate if str(style).upper()=="MAKER" else taker_fee_rate);cost=2*fee*10000+max(0,finite(spread_bps))+max(0,finite(slippage_bps))+max(0,finite(market_impact_bps))+max(0,finite(adverse_selection_bps));return finite(expected_move_bps)-cost-finite(funding_bps)

def pnl_percent(side: str,entry: float,exit: float,quantity: float,margin: float,fee_rate: float=0.0,funding: float=0.0)->float:
    e,x,q,m=finite(entry),finite(exit),abs(finite(quantity)),finite(margin)
    if min(e,x,q,m)<=0:return 0.0
    gross=(x-e)*q*(1 if str(side).upper()=="LONG" else -1);commission=e*q*max(0,finite(fee_rate));return (gross-commission+finite(funding))/m*100

def position_size_from_risk(equity: float,risk_fraction: float,stop_distance_pct: float,leverage: float,max_notional: float,price: float)->Dict[str,float]:
    eq=max(0,finite(equity));frac=clamp(risk_fraction,0,1);lev=max(1,finite(leverage,1));px=max(0,finite(price));margin=eq*frac;raw_cap=float(max_notional);cap=raw_cap if math.isinf(raw_cap) else max(0,finite(raw_cap));notional=min(cap,margin*lev);qty=notional/px if px>0 else 0;stop=max(0,finite(stop_distance_pct))/100
    return {"equity":eq,"margin":margin,"notional":notional,"quantity":qty,"leverage":lev,"risk_at_stop":notional*stop,"risk_at_stop_pct_equity":notional*stop/eq*100 if eq>0 else 0}

def dynamic_exit_surface(side: str,entry: float,atr_pct: float,confidence: float,regime_multiplier: float=1.5,trailing_fraction: float=0.8)->Dict[str,float]:
    e=max(0,finite(entry));atr=max(0,finite(atr_pct));conf=clamp(confidence/100,0,1);regime=clamp(regime_multiplier,.75,3);trail=clamp(trailing_fraction,.25,1.5);tp=clamp(atr*(1.2+1.3*conf)*regime,.2,8);sl=clamp(atr*(.85+.55*(1-conf))*max(.85,regime*.85),.15,4);tr=clamp(atr*trail,.1,4)
    if str(side).upper()=="SHORT":return {"tp":e*(1-tp/100),"sl":e*(1+sl/100),"trail_pct":tr,"tp_pct":tp,"sl_pct":sl}
    return {"tp":e*(1+tp/100),"sl":e*(1-sl/100),"trail_pct":tr,"tp_pct":tp,"sl_pct":sl}
