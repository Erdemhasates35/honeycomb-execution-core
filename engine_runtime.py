#!/data/data/com.termux/files/usr/bin/python3
# -*- coding: utf-8 -*-
"""HONEYCOMB SHARED LIVE ENGINE RUNTIME.

Every engine is a thin strategy front-end over this lifecycle:
market data -> quantitative plan -> live economics -> Kelly margin -> verified
market fill -> exchange protection -> lifecycle PnL. No synthetic fills.
"""
from __future__ import annotations
import os,time,threading
from typing import Any,Dict
from live.kernel import LiveKernel,CircuitBreaker,DynamicTrailingStopEngine,load_env
from protection_bridge import ProtectionBridge
from aggressive_profit_optimizer import plan

class LiveEngineRuntime:
    def __init__(self,name:str,venue:str="usdt"):
        self.name=name
        self.env=load_env()
        if self.env.get("EXECUTION_MODE","LIVE").upper()!="LIVE" or self.env.get("LIVE_ARMED","0")!="1":
            raise RuntimeError("LIVE production execution requires EXECUTION_MODE=LIVE and LIVE_ARMED=1")
        self.venue=venue.lower()
        self.symbols=[s.strip().upper() for s in (self.env.get("LIVE_SYMBOLS") or "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,ADAUSDT,DOGEUSDT,AVAXUSDT,LINKUSDT,LTCUSDT").split(",") if s.strip()]
        self.max_positions=max(1,int(float(self.env.get("MAX_POSITIONS",self.env.get("PROFIT_MAX_POSITIONS","3")))))
        self.max_notional=max(0.0,float(self.env.get("MAX_POSITION_SIZE_USDT",self.env.get("PROFIT_MAX_NOTIONAL","500"))))
        self.interval=max(.5,float(self.env.get("ENGINE_SCAN_SEC",self.env.get("AGGRESSIVE_SCAN_SEC","12"))))
        self.kernel=LiveKernel(venue=self.venue,env=self.env,log_fn=lambda m:self.log("KERNEL "+str(m)))
        self.bridge=ProtectionBridge(self.kernel,lambda m:self.log(m))
        self.breaker=CircuitBreaker()
        self.trailer=DynamicTrailingStopEngine(self.kernel,lambda m:self.log(m))
        self.positions:Dict[str,Dict[str,Any]]={}
        self.lock=threading.RLock()
    def log(self,msg): print(time.strftime("%H:%M:%S")+" ["+self.name+"] "+str(msg),flush=True)
    def startup(self):
        self.kernel.load_exchange_info(self.symbols)
        self.kernel.position_mode()
        self.log("LIVE START symbols=%d max_positions=%d max_notional=%s"%(len(self.symbols),self.max_positions,self.max_notional))
    def _exchange_occupied(self,symbol):
        return self.kernel.position_amt(symbol)>0
    def scan(self):
        ranked=[]
        for s in self.symbols:
            if not self.breaker.allow(): break
            if s in self.positions or self._exchange_occupied(s): continue
            try:
                p=plan(s,self.kernel)
                if p: ranked.append(p)
            except Exception as exc:
                self.log("PLAN %s %s"%(s,exc))
        ranked.sort(key=lambda x:(x["expected_edge"],x["confidence"]),reverse=True)
        room=max(0,self.max_positions-len(self.positions))
        for p in ranked[:room]:
            try:self.open_one(p)
            except Exception as exc:
                self.breaker.record_failure();self.log("OPEN %s %s"%(p["symbol"],exc))
    def open_one(self,p):
        s=p["symbol"]
        if self._exchange_occupied(s): return
        res=self.kernel.open_market(s,p["side"],p["margin_pct"],p["leverage"],p["tp_pct"],p["sl_pct"],max_notional=self.max_notional)
        meta={**p,**res,"opened_ms":int(time.time()*1000),"peak":res["entry"]}
        self.positions[s]=meta
        self.trailer.register(s,res["side"],res["entry"],res["tp"],res["sl"],res.get("pos_side"))
        self.breaker.record_success()
        self.log("OPEN %s %s entry=%.8f qty=%s lev=%s edge=%.6f margin=%.3f"%(p["side"],s,res["entry"],res["qty"],res["leverage"],p["expected_edge"]))
    def manage(self):
        for s,p in list(self.positions.items()):
            try:
                amt=self.kernel.position_amt(s,p["side"])
                if amt<=0:
                    self.log("CLOSED %s exchange position=0"%s)
                    self.trailer.forget(s);self.positions.pop(s,None);continue
                mark=self.kernel.mark(s)
                self.trailer.update(s,mark)
            except Exception as exc:
                self.log("MANAGE %s %s"%(s,exc))
    def run(self):
        self.startup()
        while True:
            self.manage()
            if len(self.positions)<self.max_positions:self.scan()
            time.sleep(self.interval)
