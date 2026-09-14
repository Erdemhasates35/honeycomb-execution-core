#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Parliament decision shim with deterministic institutional financial gate."""
from __future__ import annotations
import os,sys,time
ROOT=os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:sys.path.insert(0,ROOT)
try:
    if hasattr(sys.stdout,"reconfigure"):sys.stdout.reconfigure(encoding="utf-8",errors="replace")
except Exception:pass
import alpha_core
from institutional_adapter import normalize_decision
from live.kernel import LiveKernel,load_env,CircuitBreaker
try:
    for k,v in load_env().items():os.environ.setdefault(k,v)
except Exception:pass
kernel=LiveKernel(venue=os.getenv("VENUE","usdt").lower(),log_fn=lambda m:print(m,flush=True));breaker=CircuitBreaker();SYMBOLS=[s.strip().upper() for s in os.getenv("LIVE_SYMBOLS","BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT").split(",") if s.strip()]

def scan_symbol(symbol:str)->None:
    try:equity=max(0.0,float(kernel.balance_usdt() or 0.0))
    except Exception:return
    tech=normalize_decision(symbol,kernel,equity,[] ) or {}
    print("PARLIAMENT %s allow=%s side=%s conf=%s edge_bps=%s regime=%s reason=%s"%(symbol,bool(tech.get("allow",False)),tech.get("side"),tech.get("confidence",0),tech.get("net_edge_bps"),tech.get("regime","UNKNOWN"),tech.get("reason","missing-decision-key")),flush=True)

def main()->None:
    print("SOVEREIGN PARLIAMENT ENGINE — deterministic financial authority gate active",flush=True);print("DEFENSE_ENABLED=%s"%alpha_core.DEFENSE_ENABLED,flush=True);scan_sleep=max(1.0,float(os.getenv("SCAN_SYMBOL_DELAY_SEC","1.0")));cycle_sleep=max(10.0,float(os.getenv("SCAN_INTERVAL_SEC","20")))
    while True:
        if not breaker.allow():time.sleep(2);continue
        failed=False
        for s in SYMBOLS:
            try:scan_symbol(s)
            except Exception as e:failed=True;breaker.record_failure();print("PARLIAMENT HATA %s: %s"%(s,e),flush=True)
            time.sleep(scan_sleep)
        time.sleep(max(cycle_sleep,30.0) if failed else cycle_sleep)
        if not failed:breaker.record_success()

if __name__=="__main__":main()
