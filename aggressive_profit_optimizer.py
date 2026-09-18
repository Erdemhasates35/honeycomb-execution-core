#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Canonical live signal/economic planner used by aggressive and profit engines."""
from __future__ import annotations
import math,os,statistics
from institutional_finance import kelly_fraction,net_edge_bps,dynamic_exit_surface

def f(x,name):
    try:v=float(x)
    except Exception:raise ValueError(name)
    if not math.isfinite(v):raise ValueError(name)
    return v

def ema(x,p):
    if len(x)<p:return None
    a=2/(p+1);v=sum(x[:p])/p
    for z in x[p:]:v=a*z+(1-a)*v
    return v

def rsi(c,p=14):
    if len(c)<p+1:return None
    g=[];l=[]
    for i in range(1,len(c)):
        d=c[i]-c[i-1];g.append(max(d,0));l.append(max(-d,0))
    ag=sum(g[-p:])/p;al=sum(l[-p:])/p
    return 100 if al==0 else 100-100/(1+ag/al)

def atr(h,l,c,p=14):
    if len(c)<p+1:return None
    tr=[max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1])) for i in range(1,len(c))]
    return sum(tr[-p:])/p

def adx(h,l,c,p=14):
    if len(c)<p+2:return None
    plus=[];minus=[];tr=[]
    for i in range(1,len(c)):
        up=h[i]-h[i-1];dn=l[i-1]-l[i]
        plus.append(up if up>dn and up>0 else 0);minus.append(dn if dn>up and dn>0 else 0)
        tr.append(max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1])))
    av=sum(tr[-p:])/p or 1e-12
    pi=100*sum(plus[-p:])/p/av;mi=100*sum(minus[-p:])/p/av
    return 0 if pi+mi==0 else abs(pi-mi)/(pi+mi)*100

def _raw(kernel,symbol,interval="5m",limit=160):
    d=kernel._http("GET",kernel.v["klines"],{"symbol":symbol,"interval":interval,"limit":limit},signed=False,weight=2)
    h=[f(x[2],"high") for x in d];l=[f(x[3],"low") for x in d];c=[f(x[4],"close") for x in d];v=[f(x[5],"volume") for x in d]
    if len(c)<80:raise RuntimeError("insufficient OHLCV")
    return h,l,c,v

def plan(symbol,kernel):
    h,l,c,v=_raw(kernel,symbol,"5m",160)
    px=c[-1]; e8=ema(c,8);e21=ema(c,21);e55=ema(c,55);rr=rsi(c);aa=atr(h,l,c);dx=adx(h,l,c)
    if None in (e8,e21,e55,rr,aa,dx) or aa<=0: return None
    bid,ask,mid=kernel.book(symbol); spread=(ask-bid)/mid*10000
    if spread>float(os.getenv("MAX_SPREAD_BPS","12")):return None
    trend=(1 if e8>e21 else -1)+(1 if e21>e55 else -1)
    momentum=(c[-1]/c[-4]-1)*100
    mean=(sum(c[-20:])/20); sd=statistics.pstdev(c[-20:]) or 1e-12; z=(px-mean)/sd
    reversal=-max(-1,min(1,z/2.5))
    micro=(v[-1]/(sum(v[-20:])/20 or v[-1])-1)
    raw_score=.40*trend/2 + .25*max(-1,min(1,momentum/.60)) + .20*reversal + .15*max(-1,min(1,micro))
    direction=1 if raw_score>0 else -1 if raw_score<0 else 0
    if direction==0:return None
    confidence=min(100,50+50*abs(raw_score))
    expected_move_pct=max(.05,min(3.0,aa/px*100*(1.15+abs(raw_score))))
    econ=None
    try:
        from profit_economics import market_economics
        econ=market_economics(kernel,symbol,"LONG" if direction>0 else "SHORT",1)
        edge=net_edge_bps(expected_move_pct*100,econ["maker_fee"],econ["taker_fee"],econ["spread_bps"],float(os.getenv("EXECUTION_SLIPPAGE_BPS","2")),econ["funding_bps"])/10000
    except Exception: return None
    if edge<=0:return None
    reward_risk=1.5
    p=.50+.45*abs(raw_score)
    kelly=kelly_fraction(p,reward_risk,float(os.getenv("KELLY_FRACTION","0.25")))
    quality=min(1,abs(raw_score)+max(0,edge)*20)
    exits=dynamic_exit_surface("LONG" if direction>0 else "SHORT",px,aa/px*100,quality,1.0)
    exchange_max=kernel.max_leverage_for_notional(symbol,max(1.0,float(os.getenv("MAX_POSITION_SIZE_USDT","500"))))\n    configured_max=min(exchange_max,int(float(os.getenv("MAX_LEVERAGE",str(exchange_max)))))\n    lev=max(1,min(configured_max,int(round(1+quality*(configured_max-1)))))
    return {"symbol":symbol,"side":"LONG" if direction>0 else "SHORT","score":abs(raw_score),"confidence":confidence,
            "expected_edge":edge,"expected_move_pct":expected_move_pct,"kelly":kelly,"margin_pct":min(.05,kelly),
            "leverage":lev,"tp_pct":exits["tp_pct"],"sl_pct":exits["sl_pct"],"atr_pct":aa/px*100,
            "spread_bps":spread,"regime":"TREND" if dx>=25 else "RANGE"}
def dynamic_trail(pos,mark):
    side=pos["side"];entry=pos["entry"];atr_pct=pos.get("atr_pct",.5)
    gain=((mark/entry)-1)*100 if side=="LONG" else ((entry/mark)-1)*100
    if gain<atr_pct*0.7:return None
    lock=max(.05,atr_pct*.35)
    return mark*(1-lock/100) if side=="LONG" else mark*(1+lock/100)
