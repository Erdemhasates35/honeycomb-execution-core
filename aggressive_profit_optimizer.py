#!/data/data/com.termux/files/usr/bin/python3
# -*- coding: utf-8 -*-
"""Live-only quantitative optimizer for Honeycomb's existing Helix kernel.
No synthetic market data, no paper fills, no mock execution.
"""
from __future__ import annotations
import math, os
from typing import Any, Dict, Optional

try:
    import alpha_core
except Exception:
    alpha_core = None


def _f(x: Any, d: float = 0.0) -> float:
    try:
        v = float(x)
        return v if math.isfinite(v) else d
    except Exception:
        return d


def _ema(x, p):
    if not x or len(x) < p:
        return None
    k = 2.0 / (p + 1.0)
    v = sum(x[:p]) / p
    for z in x[p:]:
        v = z * k + v * (1.0 - k)
    return v


def _atr(h, l, c, p=14):
    if len(c) < p + 1:
        return None
    tr=[]
    for i in range(1,len(c)):
        tr.append(max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1])))
    return sum(tr[-p:]) / p


def _adx(h, l, c, p=14):
    if len(c) < p + 2:
        return 0.0
    plus=[]; minus=[]; tr=[]
    for i in range(1,len(c)):
        up=h[i]-h[i-1]; dn=l[i-1]-l[i]
        plus.append(up if up>dn and up>0 else 0.0)
        minus.append(dn if dn>up and dn>0 else 0.0)
        tr.append(max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1])))
    av=sum(tr[-p:])/p
    if av<=0:return 0.0
    pdi=100*(sum(plus[-p:])/p)/av
    mdi=100*(sum(minus[-p:])/p)/av
    den=pdi+mdi
    return 0.0 if den<=0 else abs(pdi-mdi)/den*100


def _ret(c, n):
    return 0.0 if len(c)<=n or c[-n-1]==0 else (c[-1]/c[-n-1]-1.0)*100.0


def _frame(symbol: str, interval: str, limit: int=96) -> Optional[Dict[str,float]]:
    if alpha_core is None:
        return None
    d=alpha_core.klines(symbol, interval, limit)
    if not d or len(d.get("c",[]))<40:return None
    c,h,l,v=d["c"],d["h"],d["l"],d["v"]
    e9=_ema(c,9); e21=_ema(c,21); e55=_ema(c,55)
    a=_atr(h,l,c,14) or 0.0
    adx=_adx(h,l,c,14)
    vr=v[-1]/(sum(v[-20:])/20.0+1e-12)
    return {"close":c[-1],"e9":_f(e9),"e21":_f(e21),"e55":_f(e55),
            "atr":a,"atr_pct":a/c[-1]*100 if c[-1] else 0.0,
            "adx":adx,"vol":vr,"mom8":_ret(c,8),"mom20":_ret(c,20)}


def plan(symbol: str, kernel=None) -> Optional[Dict[str,Any]]:
    f5=_frame(symbol,"5m",96); f15=_frame(symbol,"15m",96); f1h=_frame(symbol,"1h",96)
    if not f5 or not f15 or not f1h:return None
    frames=(f5,f15,f1h)
    votes=[]
    for f,w in ((f5,0.45),(f15,0.35),(f1h,0.20)):
        s=0.0
        s += 1.0 if f["e9"]>f["e21"] else -1.0
        s += 0.8 if f["e21"]>f["e55"] else -0.8
        s += 0.8 if f["mom8"]>0 else -0.8
        s += 0.6 if f["mom20"]>0 else -0.6
        if f["adx"]>25:s*=1.12
        elif f["adx"]<16:s*=0.82
        votes.append(s*w)
    raw=sum(votes)
    side="LONG" if raw>0 else "SHORT"
    strength=min(1.0,abs(raw)/3.0)
    adx5=min(1.0,max(0.0,(f5["adx"]-15)/25))
    vol5=min(1.0,max(0.0,(f5["vol"]-0.75)/1.25))
    trend_alignment=(sum(1 for f in frames if (f["e9"]>f["e21"]>f["e55"]) == (side=="LONG"))/3.0)
    confidence=100.0*(0.50*strength+0.20*adx5+0.15*vol5+0.15*trend_alignment)
    atr_pct=f5["atr_pct"]
    if atr_pct<=0:return None
    base_risk=_f(os.getenv("LIVE_RISK","0.10"),0.10)
    risk=base_risk*(0.72+0.68*min(1.0,confidence/100.0))
    vol_scale=0.055/max(atr_pct,0.055)
    risk*=max(0.65,min(1.35,vol_scale))
    risk=max(0.03,min(_f(os.getenv("AGGRESSIVE_MAX_RISK","0.14"),0.14),risk))
    lev_min=int(_f(os.getenv("LEV_MIN","10"),10)); lev_max=int(_f(os.getenv("MAX_LEVERAGE","50"),50))
    lev=int(round(lev_min+(lev_max-lev_min)*min(1.0,confidence/100.0)**1.35))
    stop_mult=1.05+0.55*(1.0-confidence/100.0)
    tp_mult=1.80+1.40*(confidence/100.0)
    sl_pct=max(0.45,min(2.20,atr_pct*stop_mult))
    tp_pct=max(0.80,min(5.50,atr_pct*tp_mult))
    fee=_f(os.getenv("FEE_RATE","0.0004"),0.0004)
    slip=_f(os.getenv("SCANNER_SLIPPAGE_BPS","2.0"),2.0)/10000.0
    expected=abs(raw)*atr_pct/100.0*2.8*max(0.5,confidence/100.0)
    roundtrip=fee*2+slip
    if expected <= roundtrip*1.35:return None
    spread_bps=0.0
    if kernel is not None:
        try:
            bid,ask,_=kernel.book(symbol)
            spread_bps=max(0.0,(ask-bid)/((ask+bid)/2.0)*10000.0)
            if spread_bps>_f(os.getenv("AGGRESSIVE_MAX_SPREAD_BPS","8"),8):return None
        except Exception:
            return None
    return {"symbol":symbol,"side":side,"score":50+raw*16,"confidence":confidence,
            "risk_pct":risk,"leverage":lev,"tp_pct":tp_pct,"sl_pct":sl_pct,
            "atr_pct":atr_pct,"adx":f5["adx"],"spread_bps":spread_bps,
            "expected_edge":expected-roundtrip,"trend_alignment":trend_alignment}


def dynamic_trail(pos: Dict[str,Any], mark: float) -> Optional[float]:
    entry=_f(pos.get("entry")); side=str(pos.get("side","")); atr_pct=_f(pos.get("atr_pct"),0.0)
    if entry<=0 or mark<=0 or atr_pct<=0:return None
    if side=="LONG":
        mfe=(mark-entry)/entry*100.0
        if mfe<atr_pct*0.90:return None
        lock=max(0.12*atr_pct,0.10)
        trail=max(entry*(1+lock/100.0),mark*(1-(atr_pct*1.15)/100.0))
        old=_f(pos.get("trail_stop"),0.0)
        return trail if trail>old else None
    mfe=(entry-mark)/entry*100.0
    if mfe<atr_pct*0.90:return None
    lock=max(0.12*atr_pct,0.10)
    trail=min(entry*(1-lock/100.0),mark*(1+(atr_pct*1.15)/100.0))
    old=_f(pos.get("trail_stop"),float("inf"))
    return trail if trail<old else None
