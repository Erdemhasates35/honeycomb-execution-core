#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared portfolio/trade analytics: net PnL, margin return and drawdown metrics."""
from __future__ import annotations

import math
from typing import Any, Dict, Iterable


def finite(x: Any, default: float = 0.0) -> float:
    try:
        v=float(x)
        return v if math.isfinite(v) else default
    except (TypeError, ValueError):
        return default


def summarize_trades(rows: Iterable[Dict[str, Any]], starting_equity: float = 0.0) -> Dict[str, float]:
    net=[]; fees=0.0; funding=0.0; gross_profit=0.0; gross_loss=0.0; peak=0.0; equity=finite(starting_equity); max_dd=0.0; hold=[]; mae=[]; mfe=[]
    for r in rows:
        n=finite(r.get("net")); net.append(n); fees+=max(0.0,finite(r.get("fee"))); funding+=finite(r.get("funding")); hold.append(max(0.0,finite(r.get("hold_sec")))); mae.append(finite(r.get("mae"))); mfe.append(finite(r.get("mfe")))
        if n>0:gross_profit+=n
        elif n<0:gross_loss+=abs(n)
        equity+=n; peak=max(peak,equity); max_dd=max(max_dd,peak-equity)
    count=len(net); total=sum(net); wins=sum(1 for x in net if x>0); losses=sum(1 for x in net if x<0)
    profit_factor=(gross_profit/gross_loss) if gross_loss>0 else (float("inf") if gross_profit>0 else 0.0)
    expectancy=total/count if count else 0.0
    return {"trades":float(count),"wins":float(wins),"losses":float(losses),"win_rate_pct":wins/count*100.0 if count else 0.0,
            "net_pnl":total,"net_pnl_pct_start":total/starting_equity*100.0 if starting_equity>0 else 0.0,
            "fees":fees,"funding":funding,"profit_factor":profit_factor,"expectancy":expectancy,
            "max_drawdown":max_dd,"max_drawdown_pct":max_dd/starting_equity*100.0 if starting_equity>0 else 0.0,
            "avg_hold_sec":sum(hold)/len(hold) if hold else 0.0,"avg_mae":sum(mae)/len(mae) if mae else 0.0,
            "avg_mfe":sum(mfe)/len(mfe) if mfe else 0.0}
