#!/data/data/com.termux/files/usr/bin/python3
# -*- coding: utf-8 -*-
"""Lobster Extreme Momentum Engine.

Real Binance Futures execution through the existing LiveKernel.
Thirty+ OHLCV-derived features, 10 specialist agents, regime-adaptive
coordination, sub-second market-microstructure sampling, 50x-75x leverage,
and margin scaling up to 10% of available balance.
"""
from __future__ import annotations

import math, os, sqlite3, statistics, threading, time
from collections import deque
from typing import Any, Dict, List, Optional, Tuple

import alpha_core
from live.kernel import LiveKernel
try:
    from honeycomb_execution_guard import _get_book
except Exception:
    _get_book = None

ROOT = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.join(ROOT, ".honeycomb_runtime")
os.makedirs(RUNTIME, exist_ok=True)
DB = os.path.join(RUNTIME, "lobster_extreme.db")

SYMBOLS = [x.strip().upper() for x in os.getenv(
    "LOBSTER_SYMBOLS",
    os.getenv("LIVE_SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,ADAUSDT,DOGEUSDT,AVAXUSDT,LINKUSDT,LTCUSDT")
).split(",") if x.strip()]
MIN_LEV = 50
MAX_LEV = 75
MAX_MARGIN_PCT = 0.10
MAX_POSITIONS = int(float(os.getenv("LOBSTER_MAX_POSITIONS", "3")))
TICK_SEC = 0.05
FEATURE_REFRESH = 1.0
SCAN_REFRESH = 0.25
FEE = float(os.getenv("FEE_RATE", "0.0004"))
SLIP_BPS = float(os.getenv("LOBSTER_SLIPPAGE_BPS", "2.0"))

book_ring: Dict[str, deque] = {s: deque(maxlen=240) for s in SYMBOLS}
state: Dict[str, Dict[str, Any]] = {}
feature_cache: Dict[str, Dict[str, Any]] = {}
lock = threading.RLock()


def f(x: Any, d: float = 0.0) -> float:
    try:
        v = float(x)
        return v if math.isfinite(v) else d
    except Exception:
        return d


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def sma(a, p):
    return sum(a[-p:]) / p if len(a) >= p else None


def ema(a, p):
    if len(a) < p: return None
    k = 2.0 / (p + 1.0); v = sum(a[:p]) / p
    for x in a[p:]: v = x * k + v * (1.0 - k)
    return v


def sd(a, p):
    if len(a) < p: return None
    return statistics.pstdev(a[-p:])


def returns(c, n):
    if len(c) <= n or c[-n-1] == 0: return 0.0
    return (c[-1] / c[-n-1] - 1.0) * 100.0


def slope(a, p):
    if len(a) < p: return 0.0
    y = a[-p:]; xm = (p - 1) / 2.0; ym = sum(y) / p
    den = sum((i-xm)**2 for i in range(p)) or 1.0
    return sum((i-xm)*(v-ym) for i,v in enumerate(y)) / den


def rsi(c, p=14):
    if len(c) < p + 1: return 50.0
    g=[]; l=[]
    for i in range(1,len(c)):
        d=c[i]-c[i-1]; g.append(max(d,0)); l.append(max(-d,0))
    ag=sum(g[-p:])/p; al=sum(l[-p:])/p
    return 100.0 if al == 0 else 100.0 - 100.0/(1.0+ag/al)


def atr(h,l,c,p=14):
    if len(c) < p+1: return 0.0
    tr=[]
    for i in range(1,len(c)):
        tr.append(max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1])))
    return sum(tr[-p:])/p


def stochastic(h,l,c,p=14):
    if len(c)<p:return 50.0
    hi=max(h[-p:]); lo=min(l[-p:]); return 50.0 if hi==lo else (c[-1]-lo)/(hi-lo)*100


def williams(h,l,c,p=14):
    if len(c)<p:return -50.0
    hi=max(h[-p:]); lo=min(l[-p:]); return -50.0 if hi==lo else (hi-c[-1])/(hi-lo)*-100


def cci(h,l,c,p=20):
    if len(c)<p:return 0.0
    tp=[(h[i]+l[i]+c[i])/3 for i in range(len(c))]; m=sma(tp,p); md=sum(abs(x-m) for x in tp[-p:])/p
    return 0.0 if not md else (tp[-1]-m)/(0.015*md)


def mfi(h,l,c,v,p=14):
    if len(c)<p+1:return 50.0
    pos=neg=0.0
    for i in range(len(c)-p,len(c)):
        t=(h[i]+l[i]+c[i])/3; prev=(h[i-1]+l[i-1]+c[i-1])/3; q=t*v[i]
        if t>prev:pos+=q
        elif t<prev:neg+=q
    return 100.0 if neg==0 else 100.0-100.0/(1.0+pos/neg)


def macd(c):
    a=ema(c,12); b=ema(c,26)
    if a is None or b is None:return 0.0,0.0
    line=a-b; hist=line-(ema(c[-34:],9) or line)
    return line,hist


def adx(h,l,c,p=14):
    if len(c)<p+2:return 0.0,0.0,0.0
    plus=[];minus=[];tr=[]
    for i in range(1,len(c)):
        up=h[i]-h[i-1];dn=l[i-1]-l[i]
        plus.append(up if up>dn and up>0 else 0.0); minus.append(dn if dn>up and dn>0 else 0.0)
        tr.append(max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1])))
    av=sum(tr[-p:])/p or 1e-12; pi=100*sum(plus[-p:])/p/av; mi=100*sum(minus[-p:])/p/av
    den=pi+mi; ax=0.0 if den==0 else abs(pi-mi)/den*100
    return ax,pi,mi


def obv(c,v):
    if len(c)<2:return 0.0
    x=0.0
    for i in range(1,len(c)):
        x += v[i] if c[i]>c[i-1] else -v[i] if c[i]<c[i-1] else 0.0
    return x


def zscore(c,p=30):
    if len(c)<p:return 0.0
    m=sma(c,p); s=sd(c,p) or 1e-12; return (c[-1]-m)/s


def cmf(h,l,c,v,p=20):
    if len(c)<p:return 0.0
    mf=0.0; vol=0.0
    for i in range(len(c)-p,len(c)):
        den=h[i]-l[i]; mult=0.0 if den==0 else ((c[i]-l[i])-(h[i]-c[i]))/den
        mf+=mult*v[i];vol+=v[i]
    return mf/vol if vol else 0.0


def calc_frame(symbol, interval, limit=160):
    d=alpha_core.klines(symbol,interval,limit)
    if not d or len(d.get('c',[]))<80:return None
    c=[f(x) for x in d['c']];h=[f(x) for x in d['h']];l=[f(x) for x in d['l']];v=[f(x) for x in d['v']]
    e8=ema(c,8) or c[-1];e21=ema(c,21) or c[-1];e55=ema(c,55) or c[-1];e89=ema(c,89) or c[-1]
    a=atr(h,l,c,14); r=rsi(c,14); st=stochastic(h,l,c,14); wr=williams(h,l,c,14); cc=cci(h,l,c,20); mf=mfi(h,l,c,v,14)
    ml,mh=macd(c); ax,di_p,di_m=adx(h,l,c); s20=sd(c,20) or 0; mid=sma(c,20) or c[-1]
    bb=(c[-1]-(mid-2*s20))/(4*s20) if s20 else .5; bbw=(4*s20/mid*100) if mid else 0
    vol20=sma(v,20) or v[-1]; vr=v[-1]/(vol20+1e-12); ob=obv(c,v); obsl=slope([ob],2) if False else (1 if ob>0 else -1)
    dc_hi=max(h[-20:]);dc_lo=min(l[-20:]); z=zscore(c,30); vw=sum((h[i]+l[i]+c[i])/3*v[i] for i in range(len(c)-20,len(c)))/(sum(v[-20:]) or 1)
    atrp=a/c[-1]*100 if c[-1] else 0; rv=(statistics.pstdev([returns(c,i) for i in range(1,min(15,len(c)-1))]) if len(c)>20 else 0)
    ch=100*math.log10((sum(max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1])) for i in range(len(c)-14,len(c))) or 1)/(max(h[-14:])-min(l[-14:]) or 1))/math.log10(14)
    return {'c':c[-1],'rsi':r,'stoch':st,'wr':wr,'cci':cc,'mfi':mf,'macd':ml,'macdh':mh,'adx':ax,'dip':di_p,'dim':di_m,'e8':e8,'e21':e21,'e55':e55,'e89':e89,'bb':bb,'bbw':bbw,'atr':a,'atrp':atrp,'vr':vr,'obv':ob,'cmf':cmf(h,l,c,v),'z':z,'vwap':vw,'vwapd':(c[-1]/vw-1)*100 if vw else 0,'dc_hi':dc_hi,'dc_lo':dc_lo,'ret1':returns(c,1),'ret3':returns(c,3),'ret5':returns(c,5),'ret12':returns(c,12),'slope':slope(c,20),'chop':ch,'rv':rv,'obdir':obsl}


def micro(symbol):
    b=None
    if _get_book:
        try:b=_get_book(symbol)
        except Exception: b=None
    if not b:
        return {'bid':0,'ask':0,'mid':0,'spread':999,'imb':0,'velocity':0,'accel':0}
    bid=f(b.get('bidPrice'));ask=f(b.get('askPrice'));bq=f(b.get('bidQty'));aq=f(b.get('askQty'));mid=(bid+ask)/2
    now=time.time(); ring=book_ring[symbol]; ring.append((now,mid,bq,aq))
    imb=(bq-aq)/(bq+aq) if bq+aq else 0
    velocity=0.0;acc=0.0
    if len(ring)>=4:
        t0,m0,*_=ring[-4];t1,m1,*_=ring[-1];velocity=(m1-m0)/max(t1-t0,1e-6)/max(m1,1e-12)*100
    if len(ring)>=8:
        t0,m0,*_=ring[-8];tm,mm,*_=ring[-4];t1,m1,*_=ring[-1];v0=(mm-m0)/max(tm-t0,1e-6);v1=(m1-mm)/max(t1-tm,1e-6);acc=(v1-v0)/max(t1-tm,1e-6)
    return {'bid':bid,'ask':ask,'mid':mid,'spread':(ask-bid)/mid*10000 if mid else 999,'imb':imb,'velocity':velocity,'accel':acc}


def sgn(x):return 1 if x>0 else -1 if x<0 else 0


def agents(fr, mic):
    f5,f15,f1h=fr
    # 10 independent specialist agents, each returns direction in [-1,1].
    a1=clamp((22-f5['rsi'])/22, -1, 1) if f5['rsi']<50 else clamp((f5['rsi']-78)/22,-1,1)
    # Extreme oscillator reversal: the center is deliberately neutral.
    a1 = clamp((20-f5['rsi'])/20,-1,1) if f5['rsi']<=35 else clamp((f5['rsi']-80)/20,-1,1) if f5['rsi']>=65 else 0.0
    a2=clamp((f5['ret1']*0.35+f5['ret3']*0.25+f5['ret5']*0.20+f5['macdh']/(abs(f5['c'])*0.001+1e-12)*0.20),-1,1)
    a3=clamp(0.35*sgn(f5['e8']-f5['e21'])+0.35*sgn(f5['e21']-f5['e55'])+0.30*sgn(f15['e21']-f15['e55']),-1,1)
    a4=clamp(sgn(f5['c']-f5['dc_hi'])*0.6+sgn(f5['c']-f5['dc_lo'])*0.4,-1,1)
    a5=clamp((f5['adx']-18)/35*sgn(f5['dip']-f5['dim']),-1,1)
    a6=clamp(0.45*sgn(f5['mfi']-50)+0.30*sgn(f5['cmf'])+0.25*f5['obdir'],-1,1)*(clamp(f5['vr']/2,0,1))
    a7=clamp(-f5['z']/3.0,-1,1)
    a8=clamp(0.55*mic['imb']+0.30*sgn(mic['velocity'])+0.15*sgn(mic['accel']),-1,1)
    a9=clamp(0.45*sgn(f15['ret5'])+0.35*sgn(f15['ret12'])+0.20*sgn(f1h['ret12']),-1,1)
    cost=max(FEE*2,0.0001)+SLIP_BPS/10000
    raw_edge=(abs(f5['ret1'])+abs(f5['ret3'])+abs(f5['ret5']))/3/100
    a10=clamp((raw_edge-cost*1.8)/(cost*4+1e-12),-1,1)
    vals=[a1,a2,a3,a4,a5,a6,a7,a8,a9,a10]
    regime='EXTREME'
    if f5['adx']>=28 and f5['bbw']>=f15['bbw']*0.9: regime='TREND'
    elif f5['bbw']>f15['bbw']*1.25: regime='EXPANSION'
    elif f5['chop']>61: regime='CHOP'
    weights=[1.35,1.35,1.00,1.10,1.00,0.95,1.25,1.40,1.00,0.90]
    if regime=='TREND': weights=[0.75,1.55,1.35,1.45,1.35,1.0,0.65,1.25,1.30,1.0]
    elif regime=='EXPANSION': weights=[0.85,1.60,1.0,1.55,1.45,1.20,0.75,1.55,1.25,1.05]
    elif regime=='CHOP': weights=[1.55,0.75,0.45,0.55,0.45,0.80,1.55,1.15,0.55,0.85]
    weighted=[v*w for v,w in zip(vals,weights)]
    total=sum(weighted); norm=sum(weights); score=total/norm
    direction=sgn(score)
    aligned=sum(1 for x in vals if sgn(x)==direction and abs(x)>=0.22)
    synergy=(aligned/10.0)**2
    if aligned>=7: score=clamp(score*(1.0+0.55*synergy),-1,1)
    extreme=(f5['rsi']<=22 or f5['rsi']>=78 or f5['stoch']<=10 or f5['stoch']>=90 or abs(f5['z'])>=2.5)
    return {'score':score,'direction':direction,'aligned':aligned,'regime':regime,'extreme':extreme,'agents':vals,'weights':weights,'atrp':f5['atrp'],'bb':f5['bb'],'bbw':f5['bbw'],'rsi':f5['rsi'],'adx':f5['adx'],'spread':mic['spread'],'edge':raw_edge-cost}


def decide(symbol):
    frames=[]
    for tf in ('1m','5m','15m','1h'):
        x=calc_frame(symbol,tf,160)
        if x is None:return None
        frames.append(x)
    mic=micro(symbol)
    ag=agents((frames[1],frames[2],frames[3]),mic)
    # Extreme momentum must be confirmed by either microstructure acceleration or multi-TF momentum.
    confirm=(abs(mic['imb'])>=0.18 and sgn(mic['imb'])==ag['direction']) or (sgn(frames[1]['ret3'])==ag['direction'] and abs(frames[1]['ret3'])>0.08)
    entry_score=abs(ag['score']) + (0.12 if confirm else 0.0)
    if ag['direction']==0 or entry_score<0.66 or ag['aligned']<6:return None
    if ag['spread']>8.0:return None
    # 50x-75x dynamic leverage; margin is never above 10% of available balance.
    quality=clamp((entry_score-0.66)/0.34,0,1)
    lev=int(round(MIN_LEV+(MAX_LEV-MIN_LEV)*(quality**0.72)))
    margin_pct=clamp(0.035+0.065*quality,0.035,MAX_MARGIN_PCT)
    atrp=frames[1]['atrp']
    # ATR-scaled protection: fast enough for extreme momentum, wider in expansion.
    sl=max(0.35,min(2.40,atrp*(0.85+0.65*(1-quality))))
    tp=max(0.65,min(6.00,atrp*(2.0+2.4*quality)))
    return {'symbol':symbol,'side':'LONG' if ag['direction']>0 else 'SHORT','score':entry_score,'confidence':min(100,50+50*entry_score),'aligned':ag['aligned'],'regime':ag['regime'],'lev':lev,'margin_pct':margin_pct,'tp':tp,'sl':sl,'atrp':atrp,'edge':ag['edge'],'spread':ag['spread'],'extreme':ag['extreme'],'confirm':confirm,'agents':ag['agents']}


def db(sql,args=()):
    try:
        c=sqlite3.connect(DB,timeout=3);c.execute(sql,args);c.commit();c.close()
    except Exception:pass


def open_position(p,kernel):
    s=p['symbol']
    with lock:
        if s in state or len(state)>=MAX_POSITIONS:return
    try:
        bal=kernel.balance_usdt()
        if bal<=0:return
        notional=bal*p['margin_pct']*p['lev']
        res=kernel.open_market(s,p['side'],p['margin_pct'],p['lev'],p['tp'],p['sl'],max_notional=notional)
        pos={'symbol':s,'side':p['side'],'entry':f(res.get('entry')),'qty':f(res.get('qty')),'tp':f(res.get('tp')),'sl':f(res.get('sl')),'lev':p['lev'],'margin_pct':p['margin_pct'],'atrp':p['atrp'],'trail':0.0,'peak':f(res.get('entry')),'stage':0,'pos_side':res.get('pos_side'),'fee':f(res.get('commission')),'opened':time.time(),'last_add':0.0}
        with lock:state[s]=pos
        db('CREATE TABLE IF NOT EXISTS trades(ts REAL,symbol TEXT,side TEXT,action TEXT,entry REAL,exit REAL,qty REAL,pnl REAL,fee REAL,score REAL,lev INTEGER,margin REAL,reason TEXT)')
        db('INSERT INTO trades VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(time.time(),s,p['side'],'OPEN',pos['entry'],0,pos['qty'],0,pos['fee'],p['score'],p['lev'],p['margin_pct'],'10-agent-extreme'))
        print(time.strftime('%H:%M:%S'),'[LOBSTER] ENTER',p['side'],s,'score=%.3f'%p['score'],'agents=%d'%p['aligned'],'lev=%dx'%p['lev'],'margin=%.2f%%'%(p['margin_pct']*100),'tp=%.3f%%'%p['tp'],'sl=%.3f%%'%p['sl'],'regime='+p['regime'],flush=True)
    except Exception as e: print(time.strftime('%H:%M:%S'),'[LOBSTER] ENTER_FAIL',s,str(e),flush=True)


def manage(kernel):
    with lock: items=list(state.items())
    for s,pos in items:
        try:
            mic=micro(s);mark=mic['mid']
            if mark<=0:continue
            side=pos['side'];entry=pos['entry']
            pnlpct=(mark/entry-1)*100 if side=='LONG' else (entry/mark-1)*100
            if (side=='LONG' and mark>pos['peak']) or (side=='SHORT' and mark<pos['peak']):pos['peak']=mark
            # Profit ratchet: after 0.8R, lock; after 1.5R, trail aggressively; after 2.5R, tighten further.
            r=max(pos['sl'],0.01); stage=2 if pnlpct>=r*2.5 else 1 if pnlpct>=r*1.5 else 0
            if stage>pos['stage']:
                pos['stage']=stage
                lockpct=max(0.10,pos['atrp']*(0.20 if stage==1 else 0.38))
                pos['trail']=pos['peak']*(1-lockpct/100) if side=='LONG' else pos['peak']*(1+lockpct/100)
                try:
                    kernel.cancel_all(s);kernel.place_protect(s,side,entry,pos['tp'],pos['trail'],pos.get('pos_side'))
                except Exception:pass
            # Momentum failure exit: micro acceleration flips against a profitable extreme trade.
            flip=(mic['accel']<0 if side=='LONG' else mic['accel']>0) and pnlpct>0.35 and abs(mic['imb'])>0.22
            hit=(side=='LONG' and (mark>=pos['tp'] or mark<=pos['sl'] or (pos['trail'] and mark<=pos['trail']))) or (side=='SHORT' and (mark<=pos['tp'] or mark>=pos['sl'] or (pos['trail'] and mark>=pos['trail'])))
            if not (hit or flip):continue
            fill=kernel.close_market(s,side,pos['qty'],pos.get('pos_side'));exitp=f(fill.get('avg')) or mark;fee=f(fill.get('commission'));gross=(exitp-entry)*pos['qty'] if side=='LONG' else (entry-exitp)*pos['qty'];net=gross-pos['fee']-fee
            db('INSERT INTO trades VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(time.time(),s,side,'CLOSE',entry,exitp,pos['qty'],net,fee,0,pos['lev'],pos['margin_pct'],'trail-or-momentum'))
            with lock:state.pop(s,None)
            print(time.strftime('%H:%M:%S'),'[LOBSTER] CLOSE',s,'net=%.6f'%net,'pnl=%.4f%%'%pnlpct,'stage=%d'%pos['stage'],flush=True)
        except Exception as e:print(time.strftime('%H:%M:%S'),'[LOBSTER] MANAGE_FAIL',s,str(e),flush=True)


def main():
    kernel=LiveKernel(venue='usdt',log_fn=lambda m:print(time.strftime('%H:%M:%S'),'[LOBSTER-K]',m,flush=True))
    print(time.strftime('%H:%M:%S'),'[LOBSTER] LIVE EXTREME MOMENTUM | 10 agents | 30+ indicators | 50x-75x | margin<=10%',flush=True)
    last_feat=0;last_scan=0;cache={}
    while True:
        now=time.time()
        if now-last_feat>=FEATURE_REFRESH:
            for s in SYMBOLS:
                try:cache[s]=decide(s)
                except Exception as e: print(time.strftime('%H:%M:%S'),'[LOBSTER] SIGNAL_FAIL',s,str(e),flush=True)
            last_feat=now
        manage(kernel)
        if now-last_scan>=SCAN_REFRESH:
            ranked=[x for x in cache.values() if x]
            ranked.sort(key=lambda x:(x['score']*x['aligned']*max(x['edge'],0.000001)),reverse=True)
            for p in ranked[:MAX_POSITIONS]:open_position(p,kernel)
            last_scan=now
        time.sleep(TICK_SEC)


if __name__=='__main__':main()
