#!/data/data/com.termux/files/usr/bin/python3
# -*- coding: utf-8 -*-
"""Honeycomb Aggressive Live Engine — real Binance Futures execution only."""
from __future__ import annotations
import os,time,threading,sqlite3
from typing import Dict,Any
from live.kernel import LiveKernel
from aggressive_profit_optimizer import plan,dynamic_trail

ENV={}
ROOT=os.path.dirname(os.path.abspath(__file__))
ENV_FILE=os.path.join(ROOT,'.env')
if os.path.exists(ENV_FILE):
    with open(ENV_FILE,encoding='utf-8') as fh:
        for line in fh:
            line=line.strip()
            if line and not line.startswith('#') and '=' in line:
                k,v=line.split('=',1); ENV[k.strip()]=v.strip().split('#')[0].strip()
for k,v in os.environ.items(): ENV.setdefault(k,v)

SYMBOLS=[x.strip().upper() for x in (ENV.get('LIVE_SYMBOLS') or 'BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,ADAUSDT,DOGEUSDT,AVAXUSDT,LINKUSDT,LTCUSDT').split(',') if x.strip()]
MAX_POS=int(float(ENV.get('MAX_POSITIONS','3')))
MAX_NOTIONAL=float(ENV.get('MAX_POSITION_SIZE_USDT','500'))
SCAN=float(ENV.get('AGGRESSIVE_SCAN_SEC','12'))
DB=os.path.join(ROOT,'.honeycomb_runtime','aggressive_live.db')
os.makedirs(os.path.dirname(DB),exist_ok=True)

kernel=LiveKernel(venue='usdt',api_key=ENV.get('BINANCE_API_KEY'),api_secret=ENV.get('BINANCE_SECRET_KEY') or ENV.get('BINANCE_API_SECRET') or ENV.get('BINANCE_SECRET'),env=ENV,log_fn=lambda m: print(time.strftime('%H:%M:%S')+' [AGG-LIVE] [K] '+str(m),flush=True))
lock=threading.RLock(); positions:Dict[str,Dict[str,Any]]={}

def db(sql,args=()):
    try:
        c=sqlite3.connect(DB,timeout=3); c.execute(sql,args); c.commit(); c.close()
    except Exception: pass

def log(m): print(time.strftime('%H:%M:%S')+' [AGG-LIVE] '+str(m),flush=True)

def open_one(p):
    s=p['symbol']; side=p['side']
    with lock:
        if s in positions or len(positions)>=MAX_POS:return
    try:
        bal=kernel.balance_usdt()
        if bal<=0:return
        res=kernel.open_market(s,side,p['risk_pct'],p['leverage'],p['tp_pct'],p['sl_pct'],max_notional=MAX_NOTIONAL)
        pos={'symbol':s,'side':side,'entry':float(res['entry']),'qty':float(res['qty']),'tp':float(res['tp']),'sl':float(res['sl']),'lev':p['leverage'],'risk_pct':p['risk_pct'],'atr_pct':p['atr_pct'],'oid':res.get('oid'),'open_fee':float(res.get('commission') or 0),'trail_stop':0.0,'last_trail':0.0,'opened':time.time(),'pos_side':res.get('pos_side')}
        with lock: positions[s]=pos
        db('CREATE TABLE IF NOT EXISTS trades(ts INTEGER,symbol TEXT,side TEXT,action TEXT,entry REAL,exit REAL,qty REAL,pnl REAL,fee REAL,score REAL,confidence REAL,reason TEXT)')
        db('INSERT INTO trades VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(int(time.time()),s,side,'OPEN',pos['entry'],0,pos['qty'],0,pos['open_fee'],p['score'],p['confidence'],'aggressive_entry'))
        log('ENTER %s %s entry=%.8f qty=%s lev=%dx risk=%.3f tp=%.3f%% sl=%.3f%% conf=%.1f edge=%.6f spread=%.2fbps'%(side,s,pos['entry'],pos['qty'],p['leverage'],p['risk_pct'],p['tp_pct'],p['sl_pct'],p['confidence'],p['expected_edge'],p['spread_bps']))
    except Exception as e: log('ENTER FAIL %s: %s'%(s,e))

def manage():
    with lock: items=list(positions.items())
    for s,pos in items:
        try:
            mark=kernel.mark(s)
            if mark<=0:continue
            side=pos['side']; entry=pos['entry']; qty=pos['qty']
            if side=='LONG': hit=mark>=pos['tp'] or mark<=pos['sl'] or (pos['trail_stop']>0 and mark<=pos['trail_stop'])
            else: hit=mark<=pos['tp'] or mark>=pos['sl'] or (pos['trail_stop']>0 and mark>=pos['trail_stop'])
            newtrail=dynamic_trail(pos,mark)
            now=time.time()
            if newtrail and now-pos['last_trail']>=20:
                try:
                    kernel.cancel_all(s)
                    kernel.place_protect(s,side,entry,pos['tp'],newtrail,pos.get('pos_side'))
                    pos['trail_stop']=newtrail; pos['last_trail']=now
                    log('TRAIL %s %s mark=%.8f stop=%.8f'%(side,s,mark,newtrail))
                except Exception as e: log('TRAIL FAIL %s: %s'%(s,e))
            if not hit:continue
            fill=kernel.close_market(s,side,qty,pos.get('pos_side')); exitp=float(fill.get('avg') or mark); fee=float(fill.get('commission') or 0)
            pnl=(exitp-entry)*qty if side=='LONG' else (entry-exitp)*qty
            net=pnl-pos['open_fee']-fee
            db('INSERT INTO trades VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(int(time.time()),s,side,'CLOSE',entry,exitp,qty,net,fee,0,0,'tp_sl_trail'))
            with lock: positions.pop(s,None)
            log('CLOSE %s %s exit=%.8f gross=%.8f net=%.8f fee=%.8f'%(side,s,exitp,pnl,net,pos['open_fee']+fee))
        except Exception as e: log('MANAGE FAIL %s: %s'%(s,e))

def scan():
    ranked=[]
    for s in SYMBOLS:
        p=plan(s,kernel)
        if p: ranked.append(p)
    ranked.sort(key=lambda x:(x['confidence']*x['expected_edge']),reverse=True)
    for p in ranked[:max(1,MAX_POS)]: open_one(p)
    if ranked: log('RANK '+' | '.join('%s:%s %.1f'%(p['symbol'],p['side'],p['confidence']) for p in ranked[:5]))

def main():
    log('=== AGGRESSIVE LIVE START ===')
    log('symbols=%d max_pos=%d scan=%.1fs max_notional=%.2f'%(len(SYMBOLS),MAX_POS,SCAN,MAX_NOTIONAL))
    kernel.load_exchange_info(SYMBOLS)
    while True:
        manage()
        with lock: room=MAX_POS-len(positions)
        if room>0: scan()
        time.sleep(SCAN)

if __name__=='__main__': main()
