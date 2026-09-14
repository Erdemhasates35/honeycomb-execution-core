#!/data/data/com.termux/files/usr/bin/python3
# -*- coding: utf-8 -*-
"""HONEYCOMB PROFIT-MAX ENGINE.

Existing engine interface preserved. Financial decisions use signed expected
move, live execution costs, settlement-aware funding and 5% margin budgeting.
"""
from __future__ import annotations

import math, os, sqlite3, time
from typing import Any, Dict, Optional

from live.kernel import LiveKernel
from aggressive_profit_optimizer import plan
from institutional_finance import dynamic_exit_surface, pnl_percent
from profit_economics import market_economics, net_edge, leverage_floor, sizing, MIN_LEVERAGE, MAX_LEVERAGE

ROOT=os.path.dirname(os.path.abspath(__file__));RUNTIME=os.path.join(ROOT,".honeycomb_runtime");DB_OUT=os.path.join(RUNTIME,"profit_max.db");os.makedirs(RUNTIME,exist_ok=True)
SYMBOLS=[s.strip().upper() for s in (os.getenv("PROFIT_SYMBOLS") or os.getenv("LIVE_SYMBOLS") or "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,DOGEUSDT,AVAXUSDT,LINKUSDT,LTCUSDT").split(",") if s.strip()]
MAX_POS=int(float(os.getenv("PROFIT_MAX_POSITIONS","3")));MAX_NOTIONAL=float(os.getenv("PROFIT_MAX_NOTIONAL",os.getenv("MAX_POSITION_SIZE_USDT","500")))
RISK_FRACTION=max(0.0,min(0.05,float(os.getenv("PROFIT_MARGIN_FRACTION","0.05"))));SCAN_SEC=float(os.getenv("PROFIT_SCAN_SEC","3"));STYLE=(os.getenv("EXECUTION_STYLE","AUTO") or "AUTO").upper();MAKER_WAIT=float(os.getenv("MAKER_WAIT_SEC","1.0"));MIN_EDGE_BPS=float(os.getenv("MIN_NET_EDGE_BPS","3"))
positions:Dict[str,Dict[str,Any]]={}


def f(x:Any,d:float=0.0)->float:
    try:v=float(x);return v if math.isfinite(v) else d
    except (TypeError,ValueError):return d


def db(sql:str,args=()):
    try:
        c=sqlite3.connect(DB_OUT,timeout=3);c.execute(sql,args);c.commit();c.close()
    except Exception:pass


def ensure_column(table:str,column:str,definition:str):
    try:
        c=sqlite3.connect(DB_OUT,timeout=3);cols={r[1] for r in c.execute('PRAGMA table_info("%s")'%table)}
        if column not in cols:c.execute('ALTER TABLE "%s" ADD COLUMN %s %s'%(table,column,definition));c.commit()
        c.close()
    except Exception:pass


def init_db():
    db("CREATE TABLE IF NOT EXISTS decisions(ts REAL,symbol TEXT,side TEXT,confidence REAL,edge_bps REAL,maker_fee REAL,taker_fee REAL,funding REAL,spread_bps REAL,leverage INTEGER,style TEXT,notional REAL,source TEXT)")
    db("CREATE TABLE IF NOT EXISTS trades(ts REAL,symbol TEXT,side TEXT,action TEXT,entry REAL,exit REAL,qty REAL,gross REAL,net REAL,fee REAL,leverage INTEGER,style TEXT,reason TEXT)")
    for col,typ in (("margin_return_pct","REAL"),("funding","REAL"),("mfe","REAL"),("mae","REAL"),("hold_sec","REAL"),("implementation_shortfall_bps","REAL"),("notional","REAL"),("margin","REAL")):
        ensure_column("trades",col,typ)


def history_bonus(symbol:str,side:str)->float:
    paths=[DB_OUT,os.path.join(RUNTIME,"aggressive_live.db"),os.path.join(RUNTIME,"lobster_extreme.db"),os.path.join(ROOT,"brain.db"),os.path.join(ROOT,"quantum_nexus_v3.db")];vals=[]
    for path in paths:
        if not os.path.exists(path):continue
        try:
            c=sqlite3.connect(path,timeout=.5);tables=[r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            for t in tables:
                cols=[r[1] for r in c.execute('PRAGMA table_info("%s")'%t.replace('"','""'))]
                if "symbol" not in cols:continue
                pnlcol=next((x for x in ("net","pnl","realized_pnl","realizedPnl") if x in cols),None)
                if not pnlcol:continue
                sidecol="side" if "side" in cols else None
                q='SELECT symbol,%s%s FROM "%s" ORDER BY rowid DESC LIMIT 200'%(pnlcol,(","+sidecol if sidecol else ""),t.replace('"','""'))
                for row in c.execute(q):
                    if str(row[0]).upper()!=symbol:continue
                    if sidecol and str(row[2]).upper()!=side.upper():continue
                    vals.append(f(row[1]))
            c.close()
        except Exception:continue
    if not vals:return 0.0
    mean=sum(vals)/len(vals);return max(-0.0005,min(0.0005,mean/(abs(mean)+1.0)*0.0005))


def choose_style(econ:Dict[str,float],expected_move_pct:float)->tuple[str,float]:
    maker=net_edge(expected_move_pct,econ,"MAKER");taker=net_edge(expected_move_pct,econ,"TAKER")
    if STYLE=="MAKER":return "MAKER",maker
    if STYLE=="TAKER":return "TAKER",taker
    p=max(0.0,min(1.0,f(os.getenv("MAKER_FILL_PROBABILITY","0.55"),.55)));maker_ev=p*maker
    return ("MAKER",maker) if maker_ev>taker and maker_ev>0 else ("TAKER",taker)


def place_gtx(k:LiveKernel,symbol:str,side:str,qty:float,price:float,pos_side:Optional[str]):
    params={"symbol":symbol,"side":"BUY" if side=="LONG" else "SELL","type":"LIMIT","timeInForce":"GTX","quantity":qty,"price":k._fmt_price(symbol,price)}
    if pos_side:params["positionSide"]=pos_side
    return k._http("POST",k.v["order"],params,signed=True,weight=1,is_order=True)


def query_order(k:LiveKernel,symbol:str,oid:Any):return k._http("GET",k.v["order"],{"symbol":symbol,"orderId":oid},signed=True,weight=1)


def reconcile_exchange_positions(k:LiveKernel):
    """Recover actual exchange positions after process restart; no synthetic fills."""
    try:data=k._http("GET",k.v["position"],{},signed=True,weight=5)
    except Exception:return
    for p in data if isinstance(data,list) else []:
        s=str(p.get("symbol") or "").upper();amt=f(p.get("positionAmt"));entry=f(p.get("entryPrice"))
        if s not in SYMBOLS or abs(amt)<=0 or entry<=0:continue
        side="LONG" if amt>0 else "SHORT";lev=max(1,int(f(p.get("leverage"),MIN_LEVERAGE)));mark=f(p.get("markPrice"),entry);atr_pct=0.0
        try:
            bid,ask,mid=k.book(s);atr_pct=max(0.0,abs(ask-bid)/max(mid,1e-12)*100.0)
        except Exception:pass
        ex=dynamic_exit_surface(side,entry,max(atr_pct,0.20),70.0,1.5,.8)
        positions[s]={"symbol":s,"side":side,"entry":entry,"qty":abs(amt),"tp":ex["tp"],"sl":ex["sl"],"lev":lev,"fee":0.0,"opened":time.time(),"style":"RECONCILED","edge":0.0,"pos_side":p.get("positionSide")}


def open_trade(k:LiveKernel,p:Dict[str,Any],econ:Dict[str,float],style:str,edge:float):
    s=p["symbol"];side=p["side"]
    if s in positions or len(positions)>=MAX_POS:return
    bal=f(k.balance_usdt());lev=leverage_floor(p.get("leverage",MIN_LEVERAGE));size=sizing(bal,RISK_FRACTION,lev,MAX_NOTIONAL)
    if not size["tradable"]:return
    bid,ask,mid=k.book(s);entry_px=bid if side=="LONG" else ask;qty=k.round_step(size["notional"]/entry_px,k.get_filters(s)["stepSize"])
    if qty<k.get_filters(s)["minQty"]:return
    pos_side=side if k.position_mode() else None;k.set_margin(s,isolated=True);k.set_leverage(s,lev);oid=None;fill=None
    if style=="MAKER":
        try:
            res=place_gtx(k,s,side,qty,entry_px,pos_side);oid=res.get("orderId");time.sleep(MAKER_WAIT);od=query_order(k,s,oid);status=od.get("status","");filled=f(od.get("executedQty"))
            if status in ("NEW","PARTIALLY_FILLED") and filled<=0:
                k._http("DELETE",k.v["order"],{"symbol":s,"orderId":oid},signed=True,weight=1,is_order=True);return
            fill=k.resolve_fill(s,oid,entry_px,qty)
        except Exception:fill=None
    if fill is None:
        res=k.place_market(s,"BUY" if side=="LONG" else "SELL",qty,pos_side);oid=res.get("orderId");fill=k.resolve_fill(s,oid,entry_px,qty);style="TAKER"
    entry=f(fill.get("avg"),entry_px);atrp=max(0.0,f(p.get("atr_pct")));ex=dynamic_exit_surface(side,entry,max(atrp,0.20),f(p.get("confidence")),1.5,.8);tp,sl=ex["tp"],ex["sl"]
    k.place_protect(s,side,entry,tp,sl,pos_side)
    actual_qty=f(fill.get("qty"),qty);actual_fee=f(fill.get("commission"));positions[s]={"symbol":s,"side":side,"entry":entry,"qty":actual_qty,"tp":tp,"sl":sl,"lev":lev,"fee":actual_fee,"opened":time.time(),"style":style,"edge":edge,"pos_side":pos_side,"margin":size["margin"],"mfe":0.0,"mae":0.0}
    db("INSERT INTO trades(ts,symbol,side,action,entry,exit,qty,gross,net,fee,leverage,style,reason,margin_return_pct,funding,mfe,mae,hold_sec,implementation_shortfall_bps,notional,margin) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(time.time(),s,side,"OPEN",entry,0,actual_qty,0,0,actual_fee,lev,style,"profit-max",0,0,0,0,0,0,size["notional"],size["margin"]))


def manage(k:LiveKernel):
    for s,pos in list(positions.items()):
        try:
            mark=k.mark(s);side=pos["side"];raw=mark-pos["entry"] if side=="LONG" else pos["entry"]-mark;pos["mfe"]=max(f(pos.get("mfe")),raw*pos["qty"]);pos["mae"]=min(f(pos.get("mae")),raw*pos["qty"]);hit=(mark>=pos["tp"] or mark<=pos["sl"]) if side=="LONG" else (mark<=pos["tp"] or mark>=pos["sl"])
            if not hit:continue
            fill=k.close_market(s,side,pos["qty"],pos.get("pos_side"));exitp=f(fill.get("avg"),mark);gross=(exitp-pos["entry"])*pos["qty"] if side=="LONG" else (pos["entry"]-exitp)*pos["qty"];fee=f(fill.get("commission"));funding=0.0;net=gross-pos["fee"]-fee-funding;hold=max(0.0,time.time()-pos["opened"]);mr=pnl_percent(side,pos["entry"],exitp,pos["qty"],f(pos.get("margin")),(pos["fee"]+fee)/max(pos["entry"]*pos["qty"],1e-12),funding)
            db("INSERT INTO trades(ts,symbol,side,action,entry,exit,qty,gross,net,fee,leverage,style,reason,margin_return_pct,funding,mfe,mae,hold_sec,implementation_shortfall_bps,notional,margin) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(time.time(),s,side,"CLOSE",pos["entry"],exitp,pos["qty"],gross,net,fee,pos["lev"],pos["style"],"tp-sl",mr,funding,pos["mfe"],pos["mae"],hold,0,pos["entry"]*pos["qty"],f(pos.get("margin"))))
            positions.pop(s,None)
        except Exception:continue


def scan(k:LiveKernel):
    ranked=[]
    for s in SYMBOLS:
        try:
            p=plan(s,k)
            if not p:continue
            econ=market_economics(k,s,p["side"]);style,edge=choose_style(econ,f(p.get("expected_move_bps",0.0))/100.0);edge+=history_bonus(s,p["side"]);edge_bps=edge*10000.0
            db("INSERT INTO decisions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",(time.time(),s,p["side"],p.get("confidence",0),edge_bps,econ["maker_fee"],econ["taker_fee"],econ["funding_rate"],econ["spread_bps"],leverage_floor(p.get("leverage",MIN_LEVERAGE)),style,0,"optimizer+runtime-db"))
            if edge_bps<MIN_EDGE_BPS:continue
            p["_econ"]=econ;p["_style"]=style;p["_net_edge"]=edge;ranked.append(p)
        except Exception:continue
    ranked.sort(key=lambda x:(x["_net_edge"],x.get("confidence",0)),reverse=True)
    for p in ranked[:MAX_POS]:open_trade(k,p,p["_econ"],p["_style"],p["_net_edge"])


def main():
    init_db();k=LiveKernel(venue="usdt",log_fn=lambda m:print(time.strftime("%H:%M:%S"),"[PROFIT-K]",m,flush=True));k.load_exchange_info(SYMBOLS);k.position_mode();reconcile_exchange_positions(k)
    while True:
        manage(k)
        try:scan(k)
        except Exception:pass
        time.sleep(SCAN_SEC)

if __name__=="__main__":main()
