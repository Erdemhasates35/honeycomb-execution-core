#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Live execution economics. No static fee/funding substitution for live data."""
from __future__ import annotations
import os,time
from typing import Any,Dict
from institutional_finance import kelly_fraction,net_edge_bps,expected_move_bps

MIN_LEVERAGE=max(1,int(float(os.getenv("MIN_LEVERAGE","1"))))
MAX_LEVERAGE=max(MIN_LEVERAGE,int(float(os.getenv("MAX_LEVERAGE","75"))))
SLIPPAGE_BPS=max(0.0,float(os.getenv("EXECUTION_SLIPPAGE_BPS",os.getenv("SCANNER_SLIPPAGE_BPS","2"))))
CACHE_TTL=max(1.0,float(os.getenv("COMMISSION_CACHE_TTL_SEC","300")))
_cache={}

def _f(x,n): return float(x) if x is not None and __import__("math").isfinite(float(x)) else (_ for _ in ()).throw(ValueError(n))

def commission_rates(kernel,symbol):
    key=(kernel.venue,symbol.upper()); now=time.time()
    if key in _cache and now-_cache[key][2]<CACHE_TTL:return _cache[key][:2]
    d=kernel._http("GET",kernel.v["commission"],{"symbol":symbol},signed=True,weight=20)
    maker=max(0.0,_f(d.get("makerCommissionRate"),"maker commission"))
    taker=max(0.0,_f(d.get("takerCommissionRate"),"taker commission"))
    _cache[key]=(maker,taker,now);return maker,taker

def market_economics(kernel,symbol,side,horizon_hours=1.0):
    bid,ask,mid=kernel.book(symbol)
    maker,taker=commission_rates(kernel,symbol)
    p=kernel._http("GET",kernel.v["premium"],{"symbol":symbol},signed=False,weight=1)
    funding=_f(p.get("lastFundingRate"),"funding")
    next_ms=_f(p.get("nextFundingTime"),"next funding")
    now_ms=time.time()*1000
    horizon=max(0.0,float(horizon_hours))*3600
    next_sec=max(0.0,(next_ms-now_ms)/1000)
    settlements=0 if horizon<next_sec else 1+int((horizon-next_sec)//(8*3600))
    signed_funding=(funding if side.upper()=="LONG" else -funding)*settlements
    spread=(ask-bid)/mid*10000
    return {"bid":bid,"ask":ask,"entry_mid":mid,"spread_bps":spread,"maker_fee":maker,"taker_fee":taker,
            "funding_rate":funding,"funding_bps":signed_funding*10000,"funding_signed":signed_funding,
            "maker_roundtrip_cost":2*maker,"taker_roundtrip_cost":2*taker+spread/10000+SLIPPAGE_BPS/10000}

def net_edge(expected_move_pct,econ,style="TAKER"):
    bps=expected_move_bps(expected_move_pct,100.0,1.0)
    return net_edge_bps(bps,econ["maker_fee"],econ["taker_fee"],econ["spread_bps"] if style!="MAKER" else 0,SLIPPAGE_BPS if style!="MAKER" else 0,econ["funding_bps"],style)/10000

def leverage_floor(requested,maximum=None):
    hi=min(MAX_LEVERAGE,int(maximum)) if maximum is not None else MAX_LEVERAGE
    return max(MIN_LEVERAGE,min(hi,int(round(float(requested)))))

def sizing(balance,risk_fraction,leverage,max_notional,min_notional=5):
    b=max(0.0,float(balance)); m=b*max(0.0,float(risk_fraction)); n=min(max(0.0,float(max_notional)),m*float(leverage))
    return {"balance":b,"margin":m,"notional":n,"leverage":float(leverage),"tradable":1.0 if n>=min_notional else 0.0}
