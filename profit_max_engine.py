#!/data/data/com.termux/files/usr/bin/python3
# -*- coding: utf-8 -*-
"""HONEYCOMB PROFIT-MAX ENGINE.

Integrates the existing quantitative signal planner with live Binance
commission/funding economics, maker/taker execution selection and the local
SQLite trade history. Existing engines and files remain untouched.
"""
from __future__ import annotations

import math, os, sqlite3, time
from typing import Any, Dict, Optional

from live.kernel import LiveKernel
from aggressive_profit_optimizer import plan
from profit_economics import market_economics, net_edge, leverage_floor, sizing, MIN_LEVERAGE, MAX_LEVERAGE

ROOT = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.join(ROOT, ".honeycomb_runtime")
DB_OUT = os.path.join(RUNTIME, "profit_max.db")
os.makedirs(RUNTIME, exist_ok=True)

SYMBOLS = [s.strip().upper() for s in (os.getenv("PROFIT_SYMBOLS") or os.getenv("LIVE_SYMBOLS") or "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,DOGEUSDT,AVAXUSDT,LINKUSDT,LTCUSDT").split(",") if s.strip()]
MAX_POS = int(float(os.getenv("PROFIT_MAX_POSITIONS", "3")))
MAX_NOTIONAL = float(os.getenv("PROFIT_MAX_NOTIONAL", os.getenv("MAX_POSITION_SIZE_USDT", "500")))
RISK_FRACTION = float(os.getenv("PROFIT_MARGIN_FRACTION", os.getenv("LIVE_RISK", "0.10")))
SCAN_SEC = float(os.getenv("PROFIT_SCAN_SEC", "3"))
STYLE = (os.getenv("EXECUTION_STYLE", "AUTO") or "AUTO").upper()
MAKER_MIN_EDGE_BPS = float(os.getenv("MAKER_MIN_EDGE_BPS", "1.5"))
MAKER_WAIT = float(os.getenv("MAKER_WAIT_SEC", "1.0"))
MIN_EDGE_BPS = float(os.getenv("MIN_NET_EDGE_BPS", "3.0"))

positions: Dict[str, Dict[str, Any]] = {}


def f(x: Any, d: float = 0.0) -> float:
    try:
        v = float(x)
        return v if math.isfinite(v) else d
    except Exception:
        return d


def db(sql: str, args=()):
    try:
        c = sqlite3.connect(DB_OUT, timeout=3)
        c.execute(sql, args); c.commit(); c.close()
    except Exception:
        pass


def init_db():
    db("CREATE TABLE IF NOT EXISTS decisions(ts REAL,symbol TEXT,side TEXT,confidence REAL,edge_bps REAL,maker_fee REAL,taker_fee REAL,funding REAL,spread_bps REAL,leverage INTEGER,style TEXT,notional REAL,source TEXT)")
    db("CREATE TABLE IF NOT EXISTS trades(ts REAL,symbol TEXT,side TEXT,action TEXT,entry REAL,exit REAL,qty REAL,gross REAL,net REAL,fee REAL,leverage INTEGER,style TEXT,reason TEXT)")


def history_bonus(symbol: str, side: str) -> float:
    """Read compatible local SQLite trade tables without mutating them.

    Only recent rows with numeric pnl/net fields are used; unknown schemas are
    skipped. This turns existing DB evidence into a small adaptive prior.
    """
    paths = [DB_OUT, os.path.join(RUNTIME, "aggressive_live.db"), os.path.join(RUNTIME, "lobster_extreme.db"), os.path.join(ROOT, "brain.db"), os.path.join(ROOT, "quantum_nexus_v3.db")]
    vals=[]
    for path in paths:
        if not os.path.exists(path): continue
        try:
            c=sqlite3.connect(path,timeout=0.5)
            tables=[r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            for t in tables:
                cols=[r[1] for r in c.execute("PRAGMA table_info(%s)" % '"'+t.replace('"','""')+'"')]
                if "symbol" not in cols: continue
                pnlcol=next((x for x in ("net","pnl","realized_pnl","realizedPnl") if x in cols),None)
                sidecol="side" if "side" in cols else None
                if not pnlcol: continue
                q='SELECT symbol,%s%s FROM "%s" ORDER BY rowid DESC LIMIT 200' % (pnlcol, (","+sidecol if sidecol else ""), t.replace('"','""'))
                for row in c.execute(q):
                    if str(row[0]).upper()!=symbol: continue
                    if sidecol and str(row[1]).upper()!=side.upper(): continue
                    pv=f(row[1] if sidecol else row[1], 0.0) if sidecol else f(row[1],0.0)
                    vals.append(pv)
            c.close()
        except Exception:
            continue
    if not vals:return 0.0
    mean=sum(vals)/len(vals)
    return max(-0.0005,min(0.0005,mean/(abs(mean)+1.0)*0.0005))


def choose_style(econ: Dict[str,float], expected_move_pct: float) -> tuple[str,float]:
    maker = net_edge(expected_move_pct,econ,"MAKER")
    taker = net_edge(expected_move_pct,econ,"TAKER")
    if STYLE == "MAKER": return "MAKER", maker
    if STYLE == "TAKER": return "TAKER", taker
    maker_adv_bps=(maker-taker)*10000.0
    if maker_adv_bps >= MAKER_MIN_EDGE_BPS and maker > 0:return "MAKER",maker
    return "TAKER",taker


def place_gtx(k: LiveKernel, symbol: str, side: str, qty: float, price: float, pos_side: Optional[str]):
    params={"symbol":symbol,"side":"BUY" if side=="LONG" else "SELL","type":"LIMIT","timeInForce":"GTX","quantity":qty,"price":k._fmt_price(symbol,price)}
    if pos_side: params["positionSide"]=pos_side
    return k._http("POST",k.v["order"],params,signed=True,weight=1,is_order=True)


def query_order(k: LiveKernel, symbol: str, oid: Any):
    return k._http("GET",k.v["order"],{"symbol":symbol,"orderId":oid},signed=True,weight=1)


def open_trade(k: LiveKernel, p: Dict[str,Any], econ: Dict[str,float], style: str, edge: float):
    s=p['symbol']; side=p['side']
    if s in positions or len(positions)>=MAX_POS:return
    bal=f(k.balance_usdt())
    lev=leverage_floor(p.get('leverage',MIN_LEVERAGE))
    size=sizing(bal,RISK_FRACTION,lev,MAX_NOTIONAL)
    if not size['tradable']:
        print(time.strftime('%H:%M:%S'),'[PROFIT-MAX] SKIP',s,'available=',bal,'notional=',round(size['notional'],6),'minimum=5',flush=True)
        return
    bid,ask,mid=k.book(s); entry_px=bid if side=='LONG' else ask
    qty=k.round_step(size['notional']/entry_px,k.get_filters(s)['stepSize'])
    if qty < k.get_filters(s)['minQty']:return
    pos_side=side if k.position_mode() else None
    k.set_margin(s,isolated=True); k.set_leverage(s,lev)
    oid=None; fill=None
    if style=='MAKER':
        try:
            res=place_gtx(k,s,side,qty,entry_px,pos_side); oid=res.get('orderId'); time.sleep(MAKER_WAIT)
            od=query_order(k,s,oid); status=od.get('status',''); filled=f(od.get('executedQty'))
            if status in ('NEW','PARTIALLY_FILLED') and filled<=0:
                k._http('DELETE',k.v['order'],{'symbol':s,'orderId':oid},signed=True,weight=1,is_order=True)
                print(time.strftime('%H:%M:%S'),'[PROFIT-MAX] MAKER MISS',s,'edge_bps=%.2f'%(edge*10000),flush=True); return
            fill=k.resolve_fill(s,oid,entry_px,qty)
        except Exception as e:
            print(time.strftime('%H:%M:%S'),'[PROFIT-MAX] MAKER FALLBACK',s,str(e),flush=True)
    if fill is None:
        res=k.place_market(s,'BUY' if side=='LONG' else 'SELL',qty,pos_side); oid=res.get('orderId')
        fill=k.resolve_fill(s,oid,entry_px,qty); style='TAKER'
    entry=f(fill.get('avg'),entry_px)
    atrp=f(p.get('atr_pct'),0.2)
    tp_pct=max(0.50,min(5.50,atrp*(2.0+1.8*f(p.get('confidence'))/100.0)))
    sl_pct=max(0.30,min(2.40,atrp*(1.0+0.5*(1.0-f(p.get('confidence'))/100.0))))
    tp=entry*(1+tp_pct/100) if side=='LONG' else entry*(1-tp_pct/100)
    sl=entry*(1-sl_pct/100) if side=='LONG' else entry*(1+sl_pct/100)
    k.place_protect(s,side,entry,tp,sl,pos_side)
    positions[s]={"symbol":s,"side":side,"entry":entry,"qty":f(fill.get('qty'),qty),"tp":tp,"sl":sl,"lev":lev,"fee":f(fill.get('commission')),"opened":time.time(),"style":style,"edge":edge}
    db("INSERT INTO trades VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",(time.time(),s,side,'OPEN',entry,0,positions[s]['qty'],0,0,positions[s]['fee'],lev,style,'profit-max'))
    print(time.strftime('%H:%M:%S'),'[PROFIT-MAX] ENTER',side,s,'lev=%dx'%lev,'style='+style,'net_edge_bps=%.2f'%(edge*10000),'notional=%.4f'%size['notional'],flush=True)


def manage(k: LiveKernel):
    for s,pos in list(positions.items()):
        try:
            mark=k.mark(s); side=pos['side']; hit=(mark>=pos['tp'] or mark<=pos['sl']) if side=='LONG' else (mark<=pos['tp'] or mark>=pos['sl'])
            if not hit:continue
            fill=k.close_market(s,side,pos['qty'],pos.get('pos_side')); exitp=f(fill.get('avg'),mark); gross=(exitp-pos['entry'])*pos['qty'] if side=='LONG' else (pos['entry']-exitp)*pos['qty']; fee=f(fill.get('commission')); net=gross-pos['fee']-fee
            db("INSERT INTO trades VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",(time.time(),s,side,'CLOSE',pos['entry'],exitp,pos['qty'],gross,net,fee,pos['lev'],pos['style'],'tp-sl'))
            positions.pop(s,None); print(time.strftime('%H:%M:%S'),'[PROFIT-MAX] CLOSE',s,'net=%.8f'%net,flush=True)
        except Exception as e:print(time.strftime('%H:%M:%S'),'[PROFIT-MAX] MANAGE_FAIL',s,e,flush=True)


def scan(k: LiveKernel):
    ranked=[]
    for s in SYMBOLS:
        try:
            p=plan(s,k)
            if not p:continue
            econ=market_economics(k,s,p['side'])
            style,edge=choose_style(econ,p.get('tp_pct',p.get('atr_pct',0.0)*3.0))
            edge += history_bonus(s,p['side'])
            edge_bps=edge*10000.0
            db("INSERT INTO decisions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",(time.time(),s,p['side'],p.get('confidence',0),edge_bps,econ['maker_fee'],econ['taker_fee'],econ['funding_rate'],econ['spread_bps'],leverage_floor(p.get('leverage',MIN_LEVERAGE)),style,0,'optimizer+runtime-db'))
            if edge_bps < MIN_EDGE_BPS:continue
            p['_econ']=econ;p['_style']=style;p['_net_edge']=edge
            ranked.append(p)
        except Exception as e: print(time.strftime('%H:%M:%S'),'[PROFIT-MAX] SIGNAL_FAIL',s,e,flush=True)
    ranked.sort(key=lambda x:(x['_net_edge'],x.get('confidence',0)),reverse=True)
    for p in ranked[:MAX_POS]:open_trade(k,p,p['_econ'],p['_style'],p['_net_edge'])
    if ranked:print(time.strftime('%H:%M:%S'),'[PROFIT-MAX] RANK',' | '.join('%s:%s %.2fbps'%(x['symbol'],x['side'],x['_net_edge']*10000) for x in ranked[:5]),flush=True)


def main():
    init_db(); k=LiveKernel(venue='usdt',log_fn=lambda m:print(time.strftime('%H:%M:%S'),'[PROFIT-K]',m,flush=True)); k.load_exchange_info(SYMBOLS); k.position_mode()
    print(time.strftime('%H:%M:%S'),'[PROFIT-MAX] START min_lev=%dx max_lev=%dx style=%s symbols=%d'%(MIN_LEVERAGE,MAX_LEVERAGE,STYLE,len(SYMBOLS)),flush=True)
    while True:
        manage(k)
        try:scan(k)
        except Exception as e:print(time.strftime('%H:%M:%S'),'[PROFIT-MAX] SCAN_FAIL',e,flush=True)
        time.sleep(SCAN_SEC)

if __name__=='__main__':main()
