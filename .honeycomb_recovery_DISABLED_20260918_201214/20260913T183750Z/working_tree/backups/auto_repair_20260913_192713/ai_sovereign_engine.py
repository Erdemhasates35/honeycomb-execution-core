#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI SOVEREIGN ENGINE v2.1 — α-Coupling Production | 10 Ajan | Bağımsız | Algo Order | LIVE_ARMED"""
import os,time,json,math,hmac,hashlib,logging,threading,urllib.parse,urllib.request,urllib.error
from typing import Dict,Any,Optional,List,Tuple
from dataclasses import dataclass
from collections import deque
try: from dotenv import load_dotenv; load_dotenv()
except: pass

logging.basicConfig(level=logging.INFO,format="%(asctime)s [%(levelname)s] [AI-SOVEREIGN] %(message)s",datefmt="%H:%M:%S")
logger=logging.getLogger("AI_Sovereign")

ALPHA=0.00729735256
USE_TESTNET=os.getenv("USE_TESTNET",os.getenv("HONEYCOMB_MODE","TESTNET")).upper() in ("TRUE","1","TESTNET","YES")
LIVE_ARMED=os.getenv("LIVE_ARMED","0").strip() in ("1","true","TRUE","yes")
API_KEY=(os.getenv("BINANCE_TESTNET_API_KEY" if USE_TESTNET else "BINANCE_API_KEY") or os.getenv("BINANCE_API_KEY") or "").strip().replace('"',"").replace("'","")
API_SECRET=(os.getenv("BINANCE_TESTNET_SECRET" if USE_TESTNET else "BINANCE_SECRET_KEY") or os.getenv("BINANCE_SECRET_KEY") or os.getenv("BINANCE_SECRET") or os.getenv("BINANCE_API_SECRET") or "").strip().replace('"',"").replace("'","")
BASE_URL=(os.getenv("BINANCE_TESTNET_URL","https://testnet.binancefuture.com") if USE_TESTNET else os.getenv("BINANCE_BASE_URL",os.getenv("BINANCE_FUTURES_URL","https://fapi.binance.com"))).rstrip("/")
FEE_RATE=float(os.getenv("FEE_RATE","0.0004"))
MAX_LEVERAGE=int(float(os.getenv("TESTNET_LEVERAGE",os.getenv("MAX_LEVERAGE","20"))))
RISK_PER_TRADE=float(os.getenv("TESTNET_RISK",os.getenv("LIVE_RISK","0.05")))
TP_PCT=float(os.getenv("TESTNET_TP_M","1.2"))/100.0
SL_PCT=float(os.getenv("TESTNET_SL_P","0.8"))/100.0
SYMBOLS=[s.strip() for s in os.getenv("SOVEREIGN_SYMBOLS","BTCUSDT,ETHUSDT,SOLUSDT").split(",") if s.strip()]
RECV_WINDOW=int(os.getenv("RECV_WINDOW","8000"))
CYCLE_SEC=int(os.getenv("SOVEREIGN_CYCLE_SEC","25"))
AI_THRESHOLD=int(os.getenv("AI_CONFIDENCE_THRESHOLD","62"))
MIN_NOTIONAL=6.0

class CoreKernel:
    def __init__(self):
        self._time_offset=0
        self._fail_count=0
        self._circuit_until=0.0
        self._session=None
        try:
            import requests
            self._session=requests.Session()
            self._session.headers.update({"User-Agent":"AI-SOVEREIGN/2.1","X-MBX-APIKEY":API_KEY})
            self._use_requests=True
        except Exception:
            self._use_requests=False

    def sync_time(self):
        try:
            d=self._raw("GET","/fapi/v1/time",{},False)
            self._time_offset=int(d["serverTime"])-int(time.time()*1000)
            logger.info("TIME SYNC offset=%d",self._time_offset)
        except Exception as e:
            logger.warning("TIME SYNC FAIL: %s",e)
            self._time_offset=0

    def _sign(self,p):
        qs=urllib.parse.urlencode({k:str(v) for k,v in p.items() if v is not None},doseq=True)
        return qs+"&signature="+hmac.new(API_SECRET.encode(),qs.encode(),hashlib.sha256).hexdigest()

    def _raw(self,method,endpoint,params,signed=True):
        if signed and (not API_KEY or not API_SECRET):
            raise RuntimeError("API_KEY/SECRET eksik")
        params=dict(params or {})
        if signed:
            params["timestamp"]=int(time.time()*1000)+self._time_offset
            params["recvWindow"]=RECV_WINDOW
            body=self._sign(params)
        else:
            body=urllib.parse.urlencode({k:str(v) for k,v in params.items()},doseq=True)

        url=BASE_URL+endpoint
        headers={"X-MBX-APIKEY":API_KEY,"Content-Type":"application/x-www-form-urlencoded","User-Agent":"AI-SOVEREIGN/2.1"}

        if self._use_requests:
            if method.upper()=="GET":
                if body: url=url+"?"+body
                r=self._session.get(url,timeout=15)
            else:
                r=self._session.post(url,data=body,headers=headers,timeout=15)
            if r.status_code>=400:
                try: err=r.json()
                except: err={"code":r.status_code,"msg":r.text}
                raise urllib.error.HTTPError(url,r.status_code,str(err),hdrs=None,fp=None)
            return r.json() if r.text else {}
        else:
            data=None
            if method.upper()=="GET":
                if body: url=url+"?"+body
            else:
                data=body.encode() if body else None
            req=urllib.request.Request(url,data=data,headers=headers,method=method.upper())
            with urllib.request.urlopen(req,timeout=15) as r:
                raw=r.read().decode()
                return json.loads(raw) if raw else {}

    def http(self,method,endpoint,params=None,signed=True,retries=5):
        if time.time()<self._circuit_until:
            raise RuntimeError("CIRCUIT OPEN")
        last=None
        for i in range(retries):
            try:
                res=self._raw(method,endpoint,params or {},signed)
                self._fail_count=0
                return res
            except urllib.error.HTTPError as e:
                raw=getattr(e,"msg",str(e))
                try: err=json.loads(raw) if isinstance(raw,str) and raw.startswith("{") else {"code":e.code,"msg":raw}
                except: err={"code":getattr(e,"code",0),"msg":raw}
                code=err.get("code")
                if code in (-1021,-1022):
                    self.sync_time()
                    time.sleep(0.6*(i+1))
                    last=RuntimeError(str(err))
                    continue
                if code==-2015:
                    self._fail_count+=4
                    raise RuntimeError("API key invalid/IP restricted (-2015)")
                last=RuntimeError(f"HTTP {getattr(e,'code',0)}: {err}")
            except Exception as e:
                last=e
                time.sleep(1.2*(i+1))
            self._fail_count+=1
            if self._fail_count>=6:
                self._circuit_until=time.time()+35
                logger.error("CIRCUIT 35s")
                self._fail_count=0
        raise RuntimeError(f"request failed: {last}")

kernel=CoreKernel()

class AlphaEngine:
    @staticmethod
    def decay(raw,age,tau=180.0): return raw*math.exp(-ALPHA*age/tau)
    @staticmethod
    def vacuum(bid,ask,funding,fmean=0.0001): return (bid-ask)/(bid+ask+1e-12)+12.0*(funding-fmean)
    @staticmethod
    def alpha_lev(max_lev,vol): return max(1.0,max_lev*(ALPHA/(vol+ALPHA)))
    @staticmethod
    def cost_veto(tech,veto_conf,lam=1.8): return max(0.0,tech-lam*veto_conf*ALPHA*100)
    @staticmethod
    def toxic(agg_b,agg_s,total): return 0.0 if total<1e-9 else (agg_b-agg_s)/total

@dataclass
class Vote:
    name:str; direction:str; confidence:float; weight:float=1.0; reason:str=""

class AgentRegistry:
    def vote_all(self,symbol,price,rsi,ema_trend,vacuum,toxic,regime):
        votes=[]
        conf=70 if ema_trend=="UP" and rsi<68 else 35
        votes.append(Vote("fin_alpha","LONG" if ema_trend=="UP" else "SHORT",conf,1.1,"EMA"))
        conf=65 if rsi>72 or rsi<28 else 30
        d="SHORT" if rsi>72 else ("LONG" if rsi<28 else "FLAT")
        votes.append(Vote("fin_beta",d,conf,0.9,"RSI extreme"))
        conf=80 if rsi>75 or rsi<25 else 40
        votes.append(Vote("risk_guardian","FLAT",conf,1.3,"Koruma"))
        conf=55 if abs(rsi-50)>15 else 25
        votes.append(Vote("quant_validator",ema_trend,conf,1.0,"Sapma"))
        conf=min(90,abs(vacuum)*120)
        d="LONG" if vacuum>0.35 else ("SHORT" if vacuum<-0.35 else "FLAT")
        votes.append(Vote("liquidity_hunter",d,conf,1.2,f"V={vacuum:.2f}"))
        votes.append(Vote("vol_scaler","FLAT",50,0.7,"Vol"))
        conf=85 if abs(toxic)>0.65 else 20
        votes.append(Vote("toxic_filter","FLAT" if abs(toxic)>0.65 else ema_trend,conf,1.4,f"T={toxic:.2f}"))
        conf=60 if regime in ("TREND_UP","TREND_DOWN") else 35
        d="LONG" if regime=="TREND_UP" else ("SHORT" if regime=="TREND_DOWN" else "FLAT")
        votes.append(Vote("regime_reader",d,conf,1.0,regime))
        votes.append(Vote("cost_accountant","FLAT",45,0.8,"Fee"))
        ls=sum(v.confidence*v.weight for v in votes if v.direction=="LONG")
        ss=sum(v.confidence*v.weight for v in votes if v.direction=="SHORT")
        fs=sum(v.confidence*v.weight for v in votes if v.direction=="FLAT")
        if ls>ss and ls>fs: fd,fc="LONG",min(95,ls/8)
        elif ss>ls and ss>fs: fd,fc="SHORT",min(95,ss/8)
        else: fd,fc="FLAT",min(95,fs/8)
        votes.append(Vote("meta_orchestrator",fd,fc,1.5,"Meta"))
        return votes

class OrderExecutor:
    def __init__(self,k): self.k=k; self.open_meta={}
    def safe_qty(self,bal,price,lev,step=0.001):
        risk=bal*RISK_PER_TRADE; notional=risk*lev
        if notional<MIN_NOTIONAL: return 0.0,0.0
        qty=(notional*(1-FEE_RATE*2))/price
        qty=math.floor(qty/step)*step
        if qty*price<MIN_NOTIONAL: return 0.0,0.0
        return round(qty,6),notional
    def set_lev(self,sym,lev):
        try: self.k.http("POST","/fapi/v1/leverage",{"symbol":sym,"leverage":lev}); return True
        except Exception as e: logger.error("LEV FAIL %s: %s",sym,e); return False
    def place_market(self,sym,side,qty):
        if not LIVE_ARMED and not USE_TESTNET:
            logger.warning("LIVE_ARMED=0 → emir yok"); return {"orderId":"SIM","status":"FILLED","avgPrice":0}
        try: return self.k.http("POST","/fapi/v1/order",{"symbol":sym,"side":side,"type":"MARKET","quantity":qty})
        except Exception as e: logger.error("MARKET FAIL: %s",e); return None
    def place_protect(self,sym,direction,qty,tp,sl):
        if not LIVE_ARMED and not USE_TESTNET: logger.info("PROTECT SIM TP=%.4f SL=%.4f",tp,sl); return
        tp_side="SELL" if direction=="LONG" else "BUY"
        sl_side="SELL" if direction=="LONG" else "BUY"
        try:
            self.k.http("POST","/fapi/v1/order",{"symbol":sym,"side":tp_side,"type":"TAKE_PROFIT_MARKET","stopPrice":str(round(tp,4)),"quantity":qty,"workingType":"MARK_PRICE","reduceOnly":"true"})
            self.k.http("POST","/fapi/v1/order",{"symbol":sym,"side":sl_side,"type":"STOP_MARKET","stopPrice":str(round(sl,4)),"quantity":qty,"workingType":"MARK_PRICE","reduceOnly":"true"})
            logger.info("PROTECT OK %s TP=%.4f SL=%.4f",sym,tp,sl)
        except Exception as e: logger.error("PROTECT FAIL %s: %s",sym,e)

executor=OrderExecutor(kernel)
agents=AgentRegistry()
alpha=AlphaEngine()

def get_balance():
    try:
        acc=kernel.http("GET","/fapi/v2/account",{})
        usdt=next((a for a in (acc.get("assets") or []) if a.get("asset")=="USDT"),None)
        return float(usdt.get("availableBalance") or usdt.get("walletBalance") or 0) if usdt else 0.0
    except Exception as e: logger.error("BALANCE ERR: %s",e); return 0.0

def get_md(symbol):
    ticker=kernel.http("GET","/fapi/v1/ticker/price",{"symbol":symbol},signed=False)
    price=float(ticker["price"])
    klines=kernel.http("GET","/fapi/v1/klines",{"symbol":symbol,"interval":"15m","limit":40},signed=False)
    closes=[float(k[4]) for k in klines]
    ema9=sum(closes[-9:])/9; ema21=sum(closes[-21:])/21
    ema_trend="UP" if ema9>ema21 else "DOWN"
    deltas=[closes[i]-closes[i-1] for i in range(1,len(closes))]
    gains=[d for d in deltas[-14:] if d>0]; losses=[-d for d in deltas[-14:] if d<0]
    ag=sum(gains)/14 if gains else 0.0; al=sum(losses)/14 if losses else 1e-9
    rsi=100-(100/(1+ag/al))
    regime="TREND_UP" if ema_trend=="UP" and rsi>55 else ("TREND_DOWN" if ema_trend=="DOWN" and rsi<45 else "RANGE")
    return {"price":price,"rsi":rsi,"ema_trend":ema_trend,"regime":regime,"closes":closes}

def run_cycle():
    bal=get_balance()
    logger.info("CYCLE bal=%.4f armed=%s mode=%s",bal,LIVE_ARMED,"TESTNET" if USE_TESTNET else "LIVE")
    for sym in SYMBOLS:
        try:
            positions=kernel.http("GET","/fapi/v2/positionRisk",{"symbol":sym})
            open_pos=[p for p in positions if abs(float(p.get("positionAmt") or 0))>1e-8]
            if open_pos:
                p=open_pos[0]
                logger.info("HOLD %s amt=%s uPnL=%.4f",sym,p.get("positionAmt"),float(p.get("unRealizedProfit") or 0))
                continue
            md=get_md(sym)
            price,rsi,ema,regime=md["price"],md["rsi"],md["ema_trend"],md["regime"]
            vacuum=alpha.vacuum(1.0,1.0,0.0001); toxic=0.0
            votes=agents.vote_all(sym,price,rsi,ema,vacuum,toxic,regime)
            meta=next(v for v in votes if v.name=="meta_orchestrator")
            direction,conf=meta.direction,meta.confidence
            logger.info("SIGNAL %s %s conf=%.1f RSI=%.1f %s %s",sym,direction,conf,rsi,ema,regime)
            if direction=="FLAT" or conf<AI_THRESHOLD:
                logger.info("SKIP %s conf=%.1f",sym,conf); continue
            vol=abs(md["closes"][-1]-md["closes"][-5])/md["closes"][-5] if len(md["closes"])>5 else 0.01
            lev=int(alpha.alpha_lev(MAX_LEVERAGE,vol)); lev=max(1,min(lev,MAX_LEVERAGE))
            qty,notional=executor.safe_qty(bal,price,lev)
            if qty<=0: logger.warning("SKIP %s qty=0",sym); continue
            if not executor.set_lev(sym,lev): continue
            side="BUY" if direction=="LONG" else "SELL"
            tp=price*(1+TP_PCT) if direction=="LONG" else price*(1-TP_PCT)
            sl=price*(1-SL_PCT) if direction=="LONG" else price*(1+SL_PCT)
            logger.info("ORDER %s %s qty=%.6f lev=%dx TP=%.4f SL=%.4f",direction,sym,qty,lev,tp,sl)
            order=executor.place_market(sym,side,qty)
            if order and order.get("status") in ("FILLED","NEW","PARTIALLY_FILLED"):
                avg=float(order.get("avgPrice") or price)
                logger.info("FILLED %s id=%s avg=%.4f",sym,order.get("orderId"),avg)
                executor.open_meta[sym]={"side":direction,"entry":avg,"qty":qty,"ts":time.time()}
                executor.place_protect(sym,direction,qty,tp,sl)
            else: logger.error("REJECT %s %s",sym,order)
        except Exception as e: logger.error("SYM ERR %s: %s",sym,e)

def main():
    if not API_KEY or not API_SECRET:
        logger.error("KRİTİK: API key/secret yok"); return
    kernel.sync_time()
    logger.info("ONLINE v2.1 | mode=%s armed=%s symbols=%s lev=%dx cycle=%ds thr=%d",
                "TESTNET" if USE_TESTNET else "LIVE",LIVE_ARMED,SYMBOLS,MAX_LEVERAGE,CYCLE_SEC,AI_THRESHOLD)
    while True:
        try:
            run_cycle(); time.sleep(CYCLE_SEC)
        except KeyboardInterrupt:
            logger.info("Durduruldu."); break
        except Exception as e:
            logger.error("LOOP ERR: %s",e); time.sleep(12)

if __name__=="__main__": main()
