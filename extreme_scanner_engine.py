#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HONEYCOMB EXTREME SCANNER ENGINE — tactical reversal (LIVE)."""
from __future__ import annotations
import logging, os, sys, time
from typing import Any, Dict, List, Tuple
ROOT=os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:sys.path.insert(0,ROOT)
try:
    if hasattr(sys.stdout,"reconfigure"):sys.stdout.reconfigure(encoding="utf-8",errors="replace")
except Exception:pass
from live.kernel import LiveKernel,DynamicTrailingStopEngine,PartialProfitEngine,CircuitBreaker,CryptographicAuditLedger,load_env
import alpha_core
from institutional_adapter import normalize_decision
try:
    for _k,_v in load_env().items():os.environ.setdefault(_k,_v)
except Exception as _e:print("UYARI .env: %s"%_e,flush=True)
ACCOUNT_LABEL=os.getenv("ACCOUNT_LABEL","SCANNER-OMEGA");logging.basicConfig(level=logging.INFO,format="%(asctime)s [%(levelname)s] [OMEGA:%s] %%(message)s"%ACCOUNT_LABEL,datefmt="%H:%M:%S");log=logging.getLogger("extreme_scanner_engine")
VENUE=os.getenv("VENUE","usdt").lower()
if os.getenv("EXECUTION_MODE","LIVE").upper()!="LIVE" or os.getenv("LIVE_ARMED","0")!="1":
    raise RuntimeError("LIVE production execution requires EXECUTION_MODE=LIVE and LIVE_ARMED=1")
DEFAULT_WIDE="BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,ADAUSDT,DOGEUSDT,AVAXUSDT,LINKUSDT,LTCUSDT,DOTUSDT,TRXUSDT,ATOMUSDT,NEARUSDT";WIDE_SYMBOLS=[s.strip().upper() for s in os.getenv("WIDE_SYMBOLS",DEFAULT_WIDE).split(",") if s.strip()]
MAX_POSITIONS=int(os.getenv("SCANNER_MAX_POSITIONS","8"));SCAN_INTERVAL_SEC=float(os.getenv("SCANNER_INTERVAL_SEC","12"));SYMBOL_DELAY_SEC=float(os.getenv("SCANNER_SYMBOL_DELAY_SEC","0.35"));AUDIT_FILE=os.path.join(ROOT,os.getenv("SCANNER_AUDIT_FILE","scanner_omega_audit.jsonl"));kernel=LiveKernel(venue=VENUE,log_fn=lambda m:log.info(m));kernel.load_exchange_info(WIDE_SYMBOLS);trail_engine=DynamicTrailingStopEngine(kernel,log_fn=lambda m:log.info(m));partial_engine=PartialProfitEngine(kernel,log_fn=lambda m:log.info(m));order_breaker=CircuitBreaker(fail_threshold=4,cooldown_sec=180);audit=CryptographicAuditLedger(AUDIT_FILE);_open_meta:Dict[str,Dict[str,Any]]={}


def open_positions_list()->List[Tuple[str,str]]:return [(s,m.get("side","")) for s,m in _open_meta.items()]


def reconcile_startup()->None:
    try:data=kernel._http("GET",kernel.v["position"],{},signed=True,weight=5)
    except Exception:return
    for p in data if isinstance(data,list) else []:
        s=str(p.get("symbol") or "").upper();amt=float(p.get("positionAmt") or 0);entry=float(p.get("entryPrice") or 0)
        if s not in WIDE_SYMBOLS or abs(amt)<=0 or entry<=0:continue
        side="LONG" if amt>0 else "SHORT";lev=max(1,int(float(p.get("leverage") or 1)));mark=float(p.get("markPrice") or entry)
        atr_pct=max(.20,abs(mark-entry)/max(entry,1e-12)*100.0);tp=entry*(1+atr_pct*2.0/100.0) if side=="LONG" else entry*(1-atr_pct*2.0/100.0);sl=entry*(1-atr_pct/100.0) if side=="LONG" else entry*(1+atr_pct/100.0)
        _open_meta[s]={"side":side,"entry":entry,"qty":abs(amt),"lev":lev,"tp":tp,"sl":sl,"confidence":0,"regime":"RECONCILED","margin":0.0,"opened":time.time(),"opened_ms":int(float(p.get("updateTime") or time.time()*1000)),"mfe":0.0,"mae":0.0}


def scan_symbol(symbol:str)->None:
    if not order_breaker.allow() or len(_open_meta)>=MAX_POSITIONS or symbol in _open_meta:return
    try:equity=max(0.0,float(kernel.balance_usdt() or 0.0))
    except Exception as e:log.warning("equity: %s",e);return
    tech=normalize_decision(symbol,kernel,equity,open_positions_list())
    if not tech or not tech.get("allow"):return
    side=tech["side"];risk_pct=min(.05,max(0.0,float(tech.get("margin_fraction") or .05)));lev=max(40,min(75,int(tech.get("leverage") or 40)));tp_pct=max(.20,float(tech.get("tp_pct") or .20));sl_pct=max(.15,float(tech.get("sl_pct") or .15));max_notional=float(os.getenv("MAX_POSITION_SIZE_USDT","500"))
    try:
        res=kernel.open_market(symbol,side,risk_pct,lev,tp_pct,sl_pct,max_notional=max_notional);_open_meta[symbol]={"side":side,"entry":res["entry"],"qty":res["qty"],"lev":res["leverage"],"tp":res["tp"],"sl":res["sl"],"confidence":tech.get("confidence"),"regime":tech.get("regime"),"margin":equity*risk_pct,"opened":time.time(),"opened_ms":int(time.time()*1000),"pos_side":res.get("pos_side"),"mfe":0.0,"mae":0.0};trail_engine.register(symbol,side,res["entry"],res["tp"],res["sl"]);partial_engine.register(symbol,side,res["entry"],res["tp"],res["sl"],res["qty"],res.get("pos_side"));order_breaker.record_success();audit.append({"event":"open","symbol":symbol,"res":res,"tech":{k:tech.get(k) for k in ("confidence","net_edge_bps","expected_move_bps","regime")}})
    except Exception as e:order_breaker.record_failure();log.error("OPEN HATA %s: %s",symbol,e)


def check_closed_positions()->None:
    for symbol,meta in list(_open_meta.items()):
        try:real_amt=kernel.position_amt(symbol,meta["side"])
        except Exception:continue
        if real_amt>0:
            try:
                _,_,mid=kernel.book(symbol);pnl=(mid-meta["entry"])*meta["qty"] if meta["side"]=="LONG" else (meta["entry"]-mid)*meta["qty"];meta["mfe"]=max(meta["mfe"],pnl);meta["mae"]=min(meta["mae"],pnl);trail_engine.update(symbol,mid);partial_engine.update(symbol,mid)
            except Exception:pass
            continue
        try:
            start_ms=int(meta.get("opened_ms") or 0)
            params={"symbol":symbol,"limit":1000}
            if start_ms>0: params["startTime"]=start_ms
            trades=kernel._http("GET",kernel.v["userTrades"],params,signed=True,weight=5)
            wanted_ps=str(meta.get("pos_side") or "BOTH").upper()
            matched=[t for t in trades if int(float(t.get("time") or 0))>=start_ms and str(t.get("positionSide") or "BOTH").upper()==wanted_ps]
            if not matched: raise RuntimeError("no lifecycle fills for %s" % symbol)
            gross=sum(float(t.get("realizedPnl") or 0) for t in matched)
            commission=sum(float(t.get("commission") or 0) for t in matched)
            net=gross-commission
            alpha_core.on_trade_closed(symbol,meta["side"],net,meta.get("confidence") or 0,meta.get("regime") or "")
        except Exception as e:
            log.error("CLOSE LEDGER HATASI %s: %s",symbol,e)
            alpha_core.on_trade_closed(symbol,meta["side"],0.0,meta.get("confidence") or 0,meta.get("regime") or "")
        trail_engine.forget(symbol);partial_engine.forget(symbol);_open_meta.pop(symbol,None)


def main_loop()->None:
    reconcile_startup();log.info("exchangeInfo loaded filters=%s symbols=%s LIVE_ARMED=%s",len(getattr(kernel,"_filters",{})),len(WIDE_SYMBOLS),os.getenv("LIVE_ARMED","0"));log.info("PANEL http://127.0.0.1:%s",os.getenv("HONEYCOMB_SCANNER_PORT","8200"))
    while True:
        check_closed_positions()
        for sym in WIDE_SYMBOLS:
            try:scan_symbol(sym)
            except Exception as e:log.error("DONGU HATASI: %s",e)
            time.sleep(SYMBOL_DELAY_SEC)
        time.sleep(SCAN_INTERVAL_SEC)

if __name__=="__main__":main_loop()
