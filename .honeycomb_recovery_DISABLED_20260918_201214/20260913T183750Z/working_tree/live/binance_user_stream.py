#!/data/data/com.termux/files/usr/bin/python3
# -*- coding: utf-8 -*-
"""Authenticated Binance Futures user-data monitor.

Prints exchange-authoritative ORDER_TRADE_UPDATE / ACCOUNT_UPDATE events and
persists them to .honeycomb_runtime/live_orders.db. No secrets are printed.
Requires websocket-client (already used by the existing market guard).
"""
from __future__ import annotations

import json, os, sqlite3, threading, time, urllib.parse, urllib.request

ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNTIME=os.path.join(ROOT,'.honeycomb_runtime'); os.makedirs(RUNTIME,exist_ok=True)
DB=os.path.join(RUNTIME,'live_orders.db')


def env():
    d={}
    p=os.path.join(ROOT,'.env')
    if os.path.exists(p):
        for line in open(p,encoding='utf-8',errors='ignore'):
            line=line.strip()
            if line and not line.startswith('#') and '=' in line:
                k,v=line.split('=',1); d[k.strip()]=v.strip().split('#')[0].strip()
    d.update({k:v for k,v in os.environ.items() if k not in d})
    return d

E=env()
KEY=(E.get('BINANCE_API_KEY') or E.get('API_KEY') or '').strip()
VENUE=(E.get('VENUE') or 'usdt').lower()
BASE='https://dapi.binance.com' if VENUE in ('coin','coin_m','coin-m') or 'COIN' in (E.get('FUTURES_MARKET') or '').upper() else 'https://fapi.binance.com'
WS='wss://dstream.binance.com/ws/' if BASE.startswith('https://dapi') else 'wss://fstream.binance.com/ws/'
LOCK=threading.Lock()


def db():
    c=sqlite3.connect(DB,timeout=5)
    c.execute('CREATE TABLE IF NOT EXISTS events(ts REAL,event TEXT,symbol TEXT,order_id TEXT,status TEXT,exec_type TEXT,last_qty REAL,last_price REAL,acc_qty REAL,commission REAL,realized_pnl REAL,payload TEXT)')
    c.commit(); return c


def listen_key():
    path='/dapi/v1/listenKey' if BASE.startswith('https://dapi') else '/fapi/v1/listenKey'
    req=urllib.request.Request(BASE+path,data=b'',headers={'X-MBX-APIKEY':KEY},method='POST')
    with urllib.request.urlopen(req,timeout=8) as r:
        return json.loads(r.read().decode())['listenKey']


def keepalive(key):
    path='/dapi/v1/listenKey' if BASE.startswith('https://dapi') else '/fapi/v1/listenKey'
    req=urllib.request.Request(BASE+path,data=b'',headers={'X-MBX-APIKEY':KEY},method='PUT')
    try:
        with urllib.request.urlopen(req,timeout=8): pass
    except Exception as e:
        print(time.strftime('%H:%M:%S'),'[USER-WS] keepalive_fail',str(e),flush=True)


def consume(key):
    import websocket
    ws=websocket.create_connection(WS+key,timeout=30,enable_multithread=True)
    last_ping=time.time()
    print(time.strftime('%H:%M:%S'),'[USER-WS] CONNECTED venue='+VENUE,flush=True)
    try:
        while True:
            if time.time()-last_ping>=1800:
                keepalive(key); last_ping=time.time()
            raw=ws.recv()
            if not raw: raise RuntimeError('user websocket closed')
            d=json.loads(raw); ev=d.get('e')
            if ev=='ORDER_TRADE_UPDATE':
                o=d.get('o') or {}
                row=(time.time(),ev,o.get('s'),str(o.get('i') or ''),o.get('X'),o.get('x'),float(o.get('l') or 0),float(o.get('L') or 0),float(o.get('z') or 0),float(o.get('n') or 0),float(o.get('rp') or 0),json.dumps(d,separators=(',',':')))
                c=db(); c.execute('INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',row); c.commit(); c.close()
                print(time.strftime('%H:%M:%S'),'[USER-WS] ORDER',o.get('s'),'oid='+str(o.get('i')),'status='+str(o.get('X')),'exec='+str(o.get('x')),'last_qty='+str(o.get('l')),'last_px='+str(o.get('L')),'cum_qty='+str(o.get('z')),'fee='+str(o.get('n')),'realized='+str(o.get('rp')),flush=True)
            elif ev=='ACCOUNT_UPDATE':
                print(time.strftime('%H:%M:%S'),'[USER-WS] ACCOUNT_UPDATE',flush=True)
            elif ev=='listenKeyExpired':
                raise RuntimeError('listenKeyExpired')
    finally:
        try: ws.close()
        except Exception: pass


def main():
    if not KEY: raise SystemExit('BINANCE_API_KEY/API_KEY missing')
    while True:
        try:
            k=listen_key(); consume(k)
        except KeyboardInterrupt: raise
        except Exception as e:
            print(time.strftime('%H:%M:%S'),'[USER-WS] RECONNECT',str(e),flush=True)
            time.sleep(3)

if __name__=='__main__': main()
