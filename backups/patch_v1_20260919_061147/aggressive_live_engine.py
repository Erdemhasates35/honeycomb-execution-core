#!/data/data/com.termux/files/usr/bin/python3
# -*- coding: utf-8 -*-
"""Honeycomb Aggressive Live Engine — real Binance Futures execution only."""
from __future__ import annotations


# =====================================================================
# HONEYCOMB MAXIMUM PROFIT STANDARD v1 (Academic)
# Sources:
# - Moreira & Muir (2017) Volatility Targeting (JFE)
# - López de Prado (2018) Triple Barrier Method
# - Wilder (1978) ATR Adaptive Trailing
# - Thorp (1969) Fractional Kelly
# - Moskowitz, Ooi, Pedersen (2012) Time-Series Momentum
# =====================================================================

def dynamic_tp_sl_maxprofit(atr_pct, score, regime="RANGE", confidence=70.0):
    """Dinamik TP/SL — sadece net kâr maksimizasyonu."""
    try:
        atr_pct = max(0.12, min(5.0, float(atr_pct or 0.7)))
        score = float(score or 0)
        quality = max(0.0, min(1.0, (score - 50.0) / 40.0)) if score > 5 else max(0.0, min(1.0, score))
        conf = max(0.0, min(1.0, float(confidence or 70) / 100.0))
        regime = str(regime or "RANGE").upper()
        if regime in ("TREND", "TREND_UP", "TREND_DOWN"):
            tp_mult = 2.7 + 2.3 * quality * conf
            sl_mult = 0.68 + 0.38 * (1.0 - quality)
        else:
            tp_mult = 1.85 + 1.65 * quality
            sl_mult = 0.88 + 0.48 * (1.0 - quality)
        tp = max(0.65, min(8.5, atr_pct * tp_mult))
        sl = max(0.28, min(2.9, atr_pct * sl_mult))
        return round(tp, 4), round(sl, 4)
    except Exception:
        return 1.8, 0.9

def adaptive_trail_maxprofit(mfe_pct, atr_pct, stage=0):
    """MFE büyüdükçe stop'u agresif şekilde yukarı çeker."""
    try:
        mfe = max(0.0, float(mfe_pct or 0.0))
        atr_pct = max(0.12, float(atr_pct or 0.7))
        if mfe < atr_pct * 0.60:
            return 0.0
        base = atr_pct * (0.15 if stage <= 0 else 0.29 if stage == 1 else 0.46)
        lock = base + mfe * 0.24
        return round(min(mfe * 0.78, lock), 4)
    except Exception:
        return 0.0

def cost_aware_net_edge(raw_edge_or_score, atr_pct, fee=0.0004, slip_bps=2.0):
    """Fee + slippage sonrası net edge. Negatifse işlem açılmamalı."""
    try:
        gross = abs(float(raw_edge_or_score or 0.0))
        if gross > 5:
            gross = (gross / 100.0) * (float(atr_pct or 0.7) / 100.0) * 2.5
        cost = float(fee) * 2.0 + (float(slip_bps) / 10000.0)
        return gross - cost
    except Exception:
        return -1.0

def volatility_size_boost(atr_pct, confidence=70.0, base_risk=0.08):
    """Düşük volatilitede pozisyonu büyüt (Moreira-Muir)."""
    try:
        atr_pct = max(0.15, float(atr_pct or 0.8))
        scale = max(0.50, min(1.75, 0.88 / atr_pct))
        if confidence and float(confidence) > 78:
            scale *= 1.10
        return round(min(0.12, float(base_risk) * scale), 4)
    except Exception:
        return base_risk

def regime_tp_boost(regime, score):
    """Trend rejimlerinde TP mesafesini artır."""
    try:
        if str(regime or "").upper() in ("TREND", "TREND_UP", "TREND_DOWN"):
            return 1.0 + 0.38 * max(0.0, min(1.0, (float(score or 50) - 50) / 40.0))
        return 1.0
    except Exception:
        return 1.0



# =====================================================================
# MAXIMUM PROFIT LAYER (Academic — Shared)
# Moreira & Muir (2017) Volatility Targeting
# López de Prado Triple Barrier Method
# Wilder ATR Adaptive Trailing (1978)
# Thorp Fractional Kelly (1969)
# Moskowitz, Ooi, Pedersen Time-Series Momentum (2012)
# =====================================================================

def dynamic_tp_sl_maxprofit(atr_pct, score, regime="RANGE", confidence=70.0):
    """Dinamik TP/SL — sadece net kâr maksimizasyonu."""
    atr_pct = max(0.12, min(5.0, float(atr_pct or 0.7)))
    quality = max(0.0, min(1.0, (float(score) - 50.0) / 40.0)) if score > 5 else max(0.0, min(1.0, float(score)))
    conf = max(0.0, min(1.0, float(confidence) / 100.0))
    regime = str(regime).upper()
    if regime in ("TREND", "TREND_UP", "TREND_DOWN"):
        tp_mult = 2.7 + 2.3 * quality * conf
        sl_mult = 0.68 + 0.38 * (1.0 - quality)
    else:
        tp_mult = 1.85 + 1.65 * quality
        sl_mult = 0.88 + 0.48 * (1.0 - quality)
    tp = max(0.65, min(8.5, atr_pct * tp_mult))
    sl = max(0.28, min(2.9, atr_pct * sl_mult))
    return round(tp, 4), round(sl, 4)

def adaptive_trail_maxprofit(mfe_pct, atr_pct, stage=0):
    """MFE büyüdükçe stop'u agresif sıkılaştır."""
    mfe = max(0.0, float(mfe_pct or 0.0))
    atr_pct = max(0.12, float(atr_pct or 0.7))
    if mfe < atr_pct * 0.60:
        return 0.0
    base = atr_pct * (0.15 if stage <= 0 else 0.29 if stage == 1 else 0.46)
    lock = base + mfe * 0.24
    return round(min(mfe * 0.78, lock), 4)

def cost_aware_net_edge(raw_edge_or_score, atr_pct, fee=0.0004, slip_bps=2.0):
    """Fee + slippage sonrası net edge. Negatifse işlem açma."""
    gross = abs(float(raw_edge_or_score or 0.0))
    if gross > 5:  # score tarzı
        gross = (gross / 100.0) * (float(atr_pct or 0.7) / 100.0) * 2.5
    cost = float(fee) * 2.0 + (float(slip_bps) / 10000.0)
    return gross - cost

def volatility_size_boost(atr_pct, confidence=70.0, base_risk=0.08):
    """Düşük vol → daha büyük pozisyon (Moreira-Muir)."""
    atr_pct = max(0.15, float(atr_pct or 0.8))
    scale = 0.88 / atr_pct
    scale = max(0.50, min(1.75, scale))
    if confidence and float(confidence) > 78:
        scale *= 1.10
    return round(min(0.12, float(base_risk) * scale), 4)

def regime_tp_boost(regime, score):
    """Trend rejimlerinde TP mesafesini artır."""
    if str(regime).upper() in ("TREND", "TREND_UP", "TREND_DOWN"):
        return 1.0 + 0.38 * max(0.0, min(1.0, (float(score) - 50) / 40.0))
    return 1.0

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
