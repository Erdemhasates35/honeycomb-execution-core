#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared portfolio/trade analytics: net PnL, margin return and drawdown."""
from __future__ import annotations
import math
from typing import Any,Dict,Iterable

def finite(x:Any,default:float=0.0)->float:
    try:v=float(x);return v if math.isfinite(v) else default
    except (TypeError,ValueError):return default

def summarize_trades(rows:Iterable[Dict[str,Any]],starting_equity:float=0.0)->Dict[str,float]:
    net=[];fees=0.0;funding=0.0;gp=0.0;gl=0.0;peak=0.0;equity=finite(starting_equity);max_dd=0.0;hold=[];mae=[];mfe=[];margin_total=0.0
    for r in rows:
        n=finite(r.get("net"));net.append(n);fees+=max(0,finite(r.get("fee")));funding+=finite(r.get("funding"));hold.append(max(0,finite(r.get("hold_sec"))));mae.append(finite(r.get("mae")));mfe.append(finite(r.get("mfe")));margin_total+=max(0,finite(r.get("margin")))
        if n>0:gp+=n
        elif n<0:gl+=abs(n)
        equity+=n;peak=max(peak,equity);max_dd=max(max_dd,peak-equity)
    count=len(net);total=sum(net);wins=sum(1 for x in net if x>0);losses=sum(1 for x in net if x<0);pf=gp/gl if gl>0 else (float("inf") if gp>0 else 0.0)
    return {"trades":float(count),"wins":float(wins),"losses":float(losses),"win_rate_pct":wins/count*100 if count else 0.0,"net_pnl":total,"net_pnl_pct_start":total/starting_equity*100 if starting_equity>0 else 0.0,"fees":fees,"funding":funding,"cost_pct_net":(fees+max(0,funding))/max(abs(total),1e-12)*100 if total else 0.0,"profit_factor":pf,"expectancy":total/count if count else 0.0,"max_drawdown":max_dd,"max_drawdown_pct":max_dd/starting_equity*100 if starting_equity>0 else 0.0,"avg_hold_sec":sum(hold)/len(hold) if hold else 0.0,"avg_mae":sum(mae)/len(mae) if mae else 0.0,"avg_mfe":sum(mfe)/len(mfe) if mfe else 0.0,"margin_deployed":margin_total,"net_pnl_pct_margin":total/margin_total*100 if margin_total>0 else 0.0}
