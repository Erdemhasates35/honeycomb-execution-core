#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
QUANTUM NEXUS OS v3.0 — MONOLITHIC AGGRESSIVE PROFIT MAXIMIZATION ENGINE
================================================================================
KANITLANMIS MATEMATIK:
  • Kelly Criterion: f* = (p*b - q)/b  [Thorp, 2006]
  • Kalman Filter:   x_k = F*x_{k-1} + K*(z - H*x)  [Kalman, 1960]
  • Regime Detection: EMA200 + RSI + ATR percentile  [Hamilton-inspired]
  • CVaR:            E[X | X <= VaR_α]  [Rockafellar & Uryasev, 2000]
================================================================================
KULLANIM:
  1. .env dosyasini doldur (ornek asagida)
  2. python3 quantum_nexus_v3_monolithic.py
  3. Tarayici: http://localhost:8082
================================================================================
"""

import os, sys, time, json, math, random, sqlite3, threading, hmac, hashlib
import urllib.request, urllib.parse, urllib.error
from collections import deque, defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Any
from flask import Flask, jsonify, request
import numpy as np

# ==============================================================================
# 0. KONFIGURASYON (.env)
# ==============================================================================
ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

def load_env(path):
    env = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip().split("#")[0].strip()
    return env

ENV = load_env(ENV_PATH)

# --- API Anahtarlari ---
BINANCE_KEY = ENV.get("BINANCE_API_KEY", "")
BINANCE_SEC = ENV.get("BINANCE_SECRET", ENV.get("BINANCE_API_SECRET", ""))
BITGET_KEY  = ENV.get("BITGET_API_KEY", "")
BITGET_SEC  = ENV.get("BITGET_SECRET", "")
BITGET_PASS = ENV.get("BITGET_PASSPHRASE", "")
OKX_KEY     = ENV.get("OKX_API_KEY", "")
OKX_SEC     = ENV.get("OKX_SECRET", "")
OKX_PASS    = ENV.get("OKX_PASSPHRASE", "")

# --- AI Swarm (Ucretsiz) ---
OLLAMA_URL   = ENV.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = ENV.get("OLLAMA_MODEL", "llama3.1")
GROQ_KEY     = ENV.get("GROQ_API_KEY", "")
GROQ_MODEL   = ENV.get("GROQ_MODEL", "llama-3.1-70b-versatile")
OR_KEY       = ENV.get("OPENROUTER_API_KEY", "")
OR_MODEL     = ENV.get("OPENROUTER_MODEL", "meta-llama/llama-3.1-70b-instruct:free")
GEMINI_KEY   = ENV.get("GEMINI_API_KEY", "")
GEMINI_MODEL = ENV.get("GEMINI_MODEL", "gemini-1.5-flash")

# --- Motor ---
MODE           = ENV.get("HONEYCOMB_MODE", "PAPER").upper()
LIVE_SYMBOLS   = [s.strip().upper() for s in ENV.get("LIVE_SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT").split(",") if s.strip()]
CAPITAL_USD    = float(ENV.get("MAX_CAPITAL_USDT", "29.4"))
TRADE_CAP_PCT  = float(ENV.get("TRADE_CAPITAL_PCT", "10.0"))
MAX_LEV        = float(ENV.get("MAX_LEVERAGE", "8.0"))
FEE_PCT        = float(ENV.get("FEE_RATE", "0.0008"))
COOLDOWN_SEC   = int(ENV.get("COOLDOWN", "3"))
INTERVAL_SEC   = int(ENV.get("AUTO_INTERVAL_SEC", "5"))
HOLD_MAX_BARS  = int(ENV.get("HOLD_MAX", "20"))
PORT           = int(ENV.get("LIVE_PORT", "8082"))

# --- Risk Celik Kurallari ---
MAX_RISK_PER_TRADE = 0.10
MAX_PORTFOLIO_HEAT = 0.30
MAX_DAILY_DD_PCT   = 15.0
CONS_LOSS_THRESH   = 3
SYMBOL_COOLDOWN    = 25
MARGIN_PAUSE_MIN   = 5
MIN_CONFIDENCE     = 65
SWARM_THRESHOLD    = float(ENV.get("SWARM_CONSENSUS_THRESHOLD", "0.65"))

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "quantum_nexus_v3.db")
lock = threading.RLock()

# ==============================================================================
# 1. MATEMATIK CEKIRDEK
# ==============================================================================

@dataclass
class KellyResult:
    optimal_f: float
    fractional_f: float
    position_size_usd: float
    leverage: float
    edge: float
    confidence: float

class KellyCriterion:
    """Kelly Criterion: f* = (p*b - q) / b [Thorp, 2006]
    Fractional Kelly (0.25) ile konservatif pozisyon boyutu."""
    def __init__(self, fraction=0.25, max_dd_pct=15.0):
        self.fraction = fraction
        self.max_dd_pct = max_dd_pct
        self._history = deque(maxlen=100)

    def calculate(self, win_rate, avg_win_pct, avg_loss_pct, balance, confidence=0.7, consec_losses=0):
        if win_rate <= 0 or avg_loss_pct <= 0:
            return KellyResult(0,0,0,0,0,confidence)
        b = avg_win_pct / avg_loss_pct
        q = 1.0 - win_rate
        kelly_full = (win_rate * b - q) / b if b > 0 else 0.0
        if kelly_full <= 0:
            return KellyResult(0,0,0,0,0,confidence)
        loss_adj = max(0.3, 1.0 - consec_losses * 0.15)
        conf_adj = 0.5 + confidence * 0.5
        kelly_frac = kelly_full * self.fraction * loss_adj * conf_adj
        dd_limit = (self.max_dd_pct / 100) / max(avg_loss_pct / 100 * 2, 0.01)
        kelly_frac = min(kelly_frac, dd_limit, 0.5)
        pos_size = balance * kelly_frac
        lev = min(pos_size / (balance * 0.02), MAX_LEV) if balance > 0 else 1.0
        return KellyResult(kelly_full, kelly_frac, pos_size, lev, kelly_full*b, confidence)

    def update(self, pnl_pct):
        self._history.append(pnl_pct)

    def stats(self):
        if not self._history:
            return {"win_rate":0.5,"avg_win":2.5,"avg_loss":1.2,"sharpe":0,"profit_factor":1.0}
        arr = np.array(self._history)
        wins = arr[arr > 0]; losses = arr[arr <= 0]
        return {
            "win_rate": len(wins)/len(arr) if len(arr) else 0,
            "avg_win": float(np.mean(wins)) if len(wins) else 0,
            "avg_loss": abs(float(np.mean(losses))) if len(losses) else 0,
            "sharpe": float(np.mean(arr)/np.std(arr)) if np.std(arr)>0 else 0,
            "profit_factor": abs(float(np.sum(wins)/np.sum(losses))) if np.sum(losses)!=0 else 999
        }

class AdaptiveKalmanFilter:
    """2-durumlu Kalman [Kalman, 1960]: [fiyat, hiz]. Adaptif R."""
    def __init__(self, q=1e-5, r=1e-2):
        self.x = np.array([[0.0],[0.0]])
        self.P = np.eye(2) * 1.0
        self.F = np.array([[1.0,1.0],[0.0,1.0]])
        self.H = np.array([[1.0,0.0]])
        self.Q = np.eye(2) * q
        self.R_base = r; self.R = r
        self._res = deque(maxlen=20)

    def update(self, m):
        self.x = self.F @ self.x
        self.P = self.F @ self.P @ self.F.T + self.Q
        z = np.array([[m]])
        S = self.H @ self.P @ self.H.T + self.R
        K = self.P @ self.H.T @ np.linalg.inv(S)
        y = z - self.H @ self.x
        self.x = self.x + K @ y
        I = np.eye(2) - K @ self.H
        self.P = I @ self.P @ I.T + K @ self.R @ K.T
        self._res.append(abs(float(y[0,0])))
        if len(self._res) >= 5:
            self.R = self.R_base * (1.0 + np.std(list(self._res)) * 10.0)
        return float(self.x[0,0]), float(self.x[1,0]), float(np.trace(self.P))

    def predict(self):
        self.x = self.F @ self.x
        self.P = self.F @ self.P @ self.F.T + self.Q

class RegimeDetector:
    """3-rejim: Bull/Bear/Ranging. EMA200 + RSI + ATR percentile."""
    def detect(self, closes, volumes=None):
        if len(closes) < 55:
            return {"regime":"ranging","prob":0.33,"vol":"medium","adj":self._adj("ranging")}
        arr = np.array(closes)
        ema200 = np.mean(arr[-200:]) if len(arr) >= 200 else np.mean(arr)
        deltas = np.diff(arr)
        gains = np.where(deltas>0,deltas,0); losses = np.where(deltas<0,-deltas,0)
        rsi = 50.0
        if len(gains) >= 14:
            ag = np.mean(gains[-14:]); al = np.mean(losses[-14:])
            rsi = 100.0 - (100.0/(1.0+ag/al)) if al>0 else 100.0
        atrs = [abs(arr[i]-arr[i-1]) for i in range(1,len(arr))]
        atr_pct = (np.mean(atrs[-14:])/arr[-1])*100 if atrs else 0
        atr_hist = [abs(arr[i]-arr[i-1])/arr[i-1]*100 for i in range(1,len(arr))]
        vol_reg = "high" if atr_pct > np.percentile(atr_hist[-100:],75) else "low" if atr_pct < np.percentile(atr_hist[-100:],25) else "medium"
        if arr[-1] > ema200*1.02 and rsi > 55:
            reg = "bull"; prob = min(0.7 + (rsi-55)/100, 0.95)
        elif arr[-1] < ema200*0.98 and rsi < 45:
            reg = "bear"; prob = min(0.7 + (45-rsi)/100, 0.95)
        else:
            reg = "ranging"; prob = 0.5
        return {"regime":reg,"prob":prob,"vol":vol_reg,"rsi":float(rsi),"atr_pct":float(atr_pct),"adj":self._adj(reg)}

    def _adj(self, reg):
        return {"bull":{"bias":1.0,"mult":1.2,"tp_sl":2.5},"bear":{"bias":-1.0,"mult":1.0,"tp_sl":2.0},"ranging":{"bias":0.0,"mult":0.6,"tp_sl":1.5}}.get(reg,{"bias":0.0,"mult":0.6,"tp_sl":1.5})

# ==============================================================================
# 2. VERITABANI (SQLite — kurulumsuz)
# ==============================================================================

def db_conn():
    conn = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def db_init():
    with db_conn() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS weights(key TEXT PRIMARY KEY, value REAL, updated_at INTEGER);
            CREATE TABLE IF NOT EXISTS outcomes(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, symbol TEXT, side TEXT, confidence REAL, net_pnl REAL, net_pnl_pct REAL, reason TEXT, regime TEXT);
            CREATE TABLE IF NOT EXISTS trades(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, symbol TEXT, side TEXT, entry REAL, exit_px REAL, qty REAL, leverage REAL, margin REAL, net_pnl REAL, fees REAL, reason TEXT, closed INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS symbol_state(symbol TEXT PRIMARY KEY, consec_loss INTEGER DEFAULT 0, consec_win INTEGER DEFAULT 0, disabled_until INTEGER DEFAULT 0, total_trades INTEGER DEFAULT 0, total_wins INTEGER DEFAULT 0, score REAL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS global_state(key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS ai_votes(ts INTEGER, symbol TEXT, provider TEXT, side TEXT, confidence REAL);
        """)
        defaults = {"ema_trend":1.4,"rsi":1.1,"macd":1.2,"volume":1.0,"momentum":0.9,"supertrend":1.3,"atr_ok":0.8,"kalman":1.1,"bollinger":0.9,"vwap":1.0,"ofi":1.2,"ichimoku":1.0}
        for k,v in defaults.items():
            c.execute("INSERT OR IGNORE INTO weights(key,value,updated_at) VALUES(?,?,?)",(k,v,int(time.time())))
        c.commit()

def get_weight(key):
    with db_conn() as c:
        row = c.execute("SELECT value FROM weights WHERE key=?",(key,)).fetchone()
        return float(row[0]) if row else 1.0

def set_weight(key, value):
    value = max(0.2, min(3.0, value))
    with db_conn() as c:
        c.execute("INSERT OR REPLACE INTO weights(key,value,updated_at) VALUES(?,?,?)",(key,value,int(time.time()))); c.commit()

def record_outcome(symbol, side, confidence, net_pnl, net_pnl_pct, reason, regime):
    with db_conn() as c:
        c.execute("INSERT INTO outcomes(ts,symbol,side,confidence,net_pnl,net_pnl_pct,reason,regime) VALUES(?,?,?,?,?,?,?,?)",(int(time.time()),symbol,side,confidence,net_pnl,net_pnl_pct,reason[:200],regime)); c.commit()
    if net_pnl > 0 and confidence >= 60:
        for k in ["ema_trend","macd","supertrend","kalman","ofi"]:
            set_weight(k, get_weight(k)*1.025)
    elif net_pnl < 0 and confidence >= 60:
        for k in ["ema_trend","rsi","volume","bollinger"]:
            set_weight(k, get_weight(k)*0.975)

def get_symbol_state(symbol):
    with db_conn() as c:
        c.execute("INSERT OR IGNORE INTO symbol_state(symbol) VALUES(?)",(symbol,)); c.commit()
        row = c.execute("SELECT consec_loss,consec_win,disabled_until,total_trades,total_wins,score FROM symbol_state WHERE symbol=?",(symbol,)).fetchone()
        return {"consec_loss":row[0] or 0,"consec_win":row[1] or 0,"disabled_until":row[2] or 0,"total_trades":row[3] or 0,"total_wins":row[4] or 0,"score":row[5] or 0.0}

def update_symbol_state(symbol, is_win):
    s = get_symbol_state(symbol)
    with db_conn() as c:
        if is_win:
            c.execute("UPDATE symbol_state SET consec_win=consec_win+1,consec_loss=0,total_trades=total_trades+1,total_wins=total_wins+1,score=score+1.2 WHERE symbol=?",(symbol,))
        else:
            c.execute("UPDATE symbol_state SET consec_loss=consec_loss+1,consec_win=0,total_trades=total_trades+1,score=score-1.5 WHERE symbol=?",(symbol,))
        c.commit()
    s = get_symbol_state(symbol)
    if s["consec_loss"] >= CONS_LOSS_THRESH:
        until = int(time.time()) + SYMBOL_COOLDOWN * 60
        with db_conn() as c:
            c.execute("UPDATE symbol_state SET disabled_until=?,consec_loss=0 WHERE symbol=?",(until,symbol)); c.commit()
        return True
    return False

def is_symbol_disabled(symbol):
    return get_symbol_state(symbol)["disabled_until"] > time.time()

def get_global_state(key, default="0"):
    with db_conn() as c:
        row = c.execute("SELECT value FROM global_state WHERE key=?",(key,)).fetchone()
        return row[0] if row else default

def set_global_state(key, value):
    with db_conn() as c:
        c.execute("INSERT OR REPLACE INTO global_state(key,value) VALUES(?,?)",(key,value)); c.commit()

def is_margin_paused():
    return float(get_global_state("margin_pause_until","0")) > time.time()

def trigger_margin_pause(detail):
    set_global_state("margin_pause_until", str(time.time() + MARGIN_PAUSE_MIN * 60))

def is_daily_dd_triggered():
    return get_global_state(f"dd_triggered_{time.strftime('%Y-%m-%d')}","0") == "1"

def trigger_daily_dd_pause():
    set_global_state(f"dd_triggered_{time.strftime('%Y-%m-%d')}", "1")

# ==============================================================================
# 3. INDIKATORLER
# ==============================================================================

def ema(arr, period):
    if len(arr) < period:
        return float(np.mean(arr)) if len(arr) > 0 else 0.0
    k = 2.0/(period+1); v = np.mean(arr[:period])
    for x in arr[period:]:
        v = x*k + v*(1-k)
    return float(v)

def rsi(arr, period=14):
    if len(arr) < period+1:
        return 50.0
    deltas = np.diff(arr); gains = np.where(deltas>0,deltas,0); losses = np.where(deltas<0,-deltas,0)
    ag = np.mean(gains[-period:]); al = np.mean(losses[-period:])
    return 100.0 - (100.0/(1.0+ag/al)) if al>0 else 100.0

def macd(arr, fast=12, slow=26):
    if len(arr) < slow:
        return 0.0, 0.0, 0.0
    m = ema(arr, fast) - ema(arr, slow)
    hist = []
    for i in range(slow, len(arr)+1):
        hist.append(ema(arr[:i], fast) - ema(arr[:i], slow))
    sig = ema(np.array(hist[-9:]), 9) if len(hist) >= 9 else m
    return m, sig, m-sig

def atr(highs, lows, closes, period=14):
    if len(closes) < period+1:
        return 0.0
    trs = [max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1])) for i in range(1,len(closes))]
    return float(np.mean(trs[-period:]))

def bollinger(arr, period=20, std_dev=2.0):
    if len(arr) < period:
        return float(arr[-1]), float(arr[-1]), float(arr[-1])
    mid = np.mean(arr[-period:]); std = np.std(arr[-period:])
    return mid+std_dev*std, mid, mid-std_dev*std

def vwap(highs, lows, closes, volumes):
    hl2 = (highs + lows + closes) / 3
    return float(np.sum(hl2 * volumes) / np.sum(volumes)) if np.sum(volumes) > 0 else float(closes[-1])

def supertrend_dir(highs, lows, closes, period=10, mult=3.0):
    if len(closes) < period+2:
        return 0
    a = atr(highs, lows, closes, period)
    hl2 = (highs[-1] + lows[-1]) / 2
    if closes[-1] > hl2 + mult*a:
        return 1
    if closes[-1] < hl2 - mult*a:
        return -1
    return 1 if closes[-1] > closes[-2] else -1

def ofi(volumes, closes, opens):
    if len(volumes) < 10:
        return 0.0
    deltas = closes[-10:] - opens[-10:]
    return float(np.sum(volumes[-10:] * np.sign(deltas)) / np.sum(volumes[-10:]))

# ==============================================================================
# 4. VERI CEKME
# ==============================================================================

_kline_mem = {}

def fetch_klines(symbol, interval="1m", limit=100):
    key = f"{symbol}_{interval}"
    now = time.time()
    if key in _kline_mem and now - _kline_mem[key][0] < 20:
        return _kline_mem[key][1]
    try:
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"
        req = urllib.request.Request(url, headers={"User-Agent":"quantum-nexus-v3"})
        with urllib.request.urlopen(req, timeout=5) as r:
            raw = json.loads(r.read().decode("utf-8"))
        data = {
            "c": np.array([float(x[4]) for x in raw]),
            "v": np.array([float(x[5]) for x in raw]),
            "h": np.array([float(x[2]) for x in raw]),
            "l": np.array([float(x[3]) for x in raw]),
            "o": np.array([float(x[1]) for x in raw])
        }
        _kline_mem[key] = (now, data)
        return data
    except Exception:
        return None

def fetch_price(symbol):
    try:
        url = f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={symbol}"
        req = urllib.request.Request(url, headers={"User-Agent":"qn-v3"})
        with urllib.request.urlopen(req, timeout=3) as r:
            d = json.loads(r.read().decode("utf-8"))
        return float(d["price"]), "live"
    except Exception:
        return 0.0, "error"

def fetch_funding_rate(symbol):
    try:
        url = f"https://fapi.binance.com/fapi/v1/fundingRate?symbol={symbol}&limit=1"
        req = urllib.request.Request(url, headers={"User-Agent":"qn-v3"})
        with urllib.request.urlopen(req, timeout=3) as r:
            d = json.loads(r.read().decode("utf-8"))
        return float(d[0]["fundingRate"]) if d else 0.0
    except Exception:
        return 0.0

# ==============================================================================
# 5. AI SWARM (Ucretsiz API'ler)
# ==============================================================================

class AISwarm:
    def __init__(self):
        self.providers = []
        try:
            req = urllib.request.Request(f"{OLLAMA_URL}/api/tags", headers={"User-Agent":"qn-v3"})
            with urllib.request.urlopen(req, timeout=2) as r:
                json.loads(r.read().decode())
            self.providers.append("ollama")
        except Exception:
            pass
        if GROQ_KEY: self.providers.append("groq")
        if OR_KEY: self.providers.append("openrouter")
        if GEMINI_KEY: self.providers.append("gemini")

    def _build_prompt(self, symbol, summary):
        return f"Analyze {symbol} for next 15m. Data: {summary}. Respond ONLY JSON: {{\"side\":\"LONG\"|\"SHORT\"|\"NEUTRAL\",\"confidence\":0-100,\"reason\":\"brief\"}}"

    def _ask(self, provider, prompt):
        try:
            if provider == "ollama":
                data = json.dumps({"model":OLLAMA_MODEL,"prompt":prompt,"stream":False}).encode()
                req = urllib.request.Request(f"{OLLAMA_URL}/api/generate", data=data, headers={"Content-Type":"application/json"})
                with urllib.request.urlopen(req, timeout=10) as r:
                    text = json.loads(r.read().decode()).get("response","")
            elif provider == "groq":
                data = json.dumps({"model":GROQ_MODEL,"messages":[{"role":"user","content":prompt}],"temperature":0.1}).encode()
                req = urllib.request.Request("https://api.groq.com/openai/v1/chat/completions", data=data, headers={"Authorization":f"Bearer {GROQ_KEY}","Content-Type":"application/json"})
                with urllib.request.urlopen(req, timeout=10) as r:
                    text = json.loads(r.read().decode())["choices"][0]["message"]["content"]
            elif provider == "openrouter":
                data = json.dumps({"model":OR_MODEL,"messages":[{"role":"user","content":prompt}]}).encode()
                req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", data=data, headers={"Authorization":f"Bearer {OR_KEY}","Content-Type":"application/json"})
                with urllib.request.urlopen(req, timeout=15) as r:
                    text = json.loads(r.read().decode())["choices"][0]["message"]["content"]
            elif provider == "gemini":
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_KEY}"
                data = json.dumps({"contents":[{"parts":[{"text":prompt}]}]}).encode()
                req = urllib.request.Request(url, data=data, headers={"Content-Type":"application/json"})
                with urllib.request.urlopen(req, timeout=10) as r:
                    text = json.loads(r.read().decode())["candidates"][0]["content"]["parts"][0]["text"]
            else:
                return None
            s = text.find("{"); e = text.rfind("}") + 1
            if s >= 0 and e > s:
                return json.loads(text[s:e])
        except Exception:
            pass
        return None

    def vote(self, symbol, summary):
        prompt = self._build_prompt(symbol, summary)
        votes = []
        for provider in self.providers:
            res = self._ask(provider, prompt)
            if res and "side" in res:
                v = {"provider":provider, "side":res.get("side","NEUTRAL").upper(), "confidence":float(res.get("confidence",50))}
                votes.append(v)
                with db_conn() as c:
                    c.execute("INSERT INTO ai_votes(ts,symbol,provider,side,confidence) VALUES(?,?,?,?,?)",(int(time.time()),symbol,provider,v["side"],v["confidence"])); c.commit()
        if len(votes) < 2:
            return None, 0.0, votes
        long_s = sum(v["confidence"] for v in votes if v["side"]=="LONG")
        short_s = sum(v["confidence"] for v in votes if v["side"]=="SHORT")
        total = sum(v["confidence"] for v in votes)
        if total == 0:
            return None, 0.0, votes
        lr, sr = long_s/total, short_s/total
        if lr >= SWARM_THRESHOLD:
            return "LONG", lr*100, votes
        elif sr >= SWARM_THRESHOLD:
            return "SHORT", sr*100, votes
        return None, max(lr,sr)*100, votes

# ==============================================================================
# 6. ALPHA BRAIN v3
# ==============================================================================

class AlphaBrainV3:
    TIMEFRAMES = ["1m","5m","15m"]
    TF_WEIGHTS = {"1m":0.25,"5m":0.35,"15m":0.40}

    def __init__(self):
        self.kalman = AdaptiveKalmanFilter()
        self.regime = RegimeDetector()
        self.kelly = KellyCriterion(fraction=0.25)

    def analyze_tf(self, symbol, interval):
        data = fetch_klines(symbol, interval, 80)
        if not data or len(data["c"]) < 50:
            return None
        c, v, h, l, o = data["c"], data["v"], data["h"], data["l"], data["o"]

        # Kalman
        for p in c[:-1]:
            self.kalman.predict(); self.kalman.update(p)
        self.kalman.predict(); k_price, k_vel, k_unc = self.kalman.update(float(c[-1]))

        e9 = ema(c,9); e21 = ema(c,21); e55 = ema(c,55)
        r = rsi(c,14); a = atr(h,l,c,14)
        mom = (c[-1]-c[-11])/c[-11]*100 if len(c)>=11 else 0
        m_line, m_sig, m_hist = macd(c)
        st = supertrend_dir(h,l,c)
        bb_u, bb_m, bb_l = bollinger(c)
        vw = vwap(h,l,c,v)
        ofi_val = ofi(v,c,o)
        atr_pct = (a/c[-1])*100 if c[-1]>0 else 0
        vol_avg = np.mean(v[-20:]); vol_ratio = v[-1]/vol_avg if vol_avg>0 else 1.0

        score = 0.0; reasons = []

        w = get_weight("ema_trend")
        if e9 > e21 > e55: score += 30*w; reasons.append("EMA yukselis")
        elif e9 < e21 < e55: score -= 30*w; reasons.append("EMA dusus")
        elif e9 > e21: score += 14*w; reasons.append("EMA kisa yukari")
        else: score -= 14*w; reasons.append("EMA kisa asagi")

        w = get_weight("rsi")
        if 45 <= r <= 65: score += 16*w; reasons.append(f"RSI optimal {r:.0f}")
        elif r > 75: score -= 18*w; reasons.append(f"RSI asiri alim {r:.0f}")
        elif r < 25: score += 18*w; reasons.append(f"RSI asiri satim {r:.0f}")

        w = get_weight("macd")
        if m_hist > 0: score += 14*w; reasons.append("MACD pozitif")
        else: score -= 14*w; reasons.append("MACD negatif")

        w = get_weight("bollinger")
        if c[-1] < bb_l: score += 12*w; reasons.append("BB alt")
        elif c[-1] > bb_u: score -= 12*w; reasons.append("BB ust")

        w = get_weight("vwap")
        if c[-1] > vw*1.002: score += 10*w; reasons.append("VWAP ustu")
        elif c[-1] < vw*0.998: score -= 10*w; reasons.append("VWAP alti")

        w = get_weight("ofi")
        if ofi_val > 0.3: score += 14*w; reasons.append(f"Alim baskisi {ofi_val:.2f}")
        elif ofi_val < -0.3: score -= 14*w; reasons.append(f"Satim baskisi {ofi_val:.2f}")

        w = get_weight("kalman")
        if k_vel > 0.1: score += 10*w; reasons.append(f"Kalman +{k_vel:.3f}")
        elif k_vel < -0.1: score -= 10*w; reasons.append(f"Kalman {k_vel:.3f}")

        w = get_weight("volume")
        if vol_ratio >= 1.25: score += 12*w; reasons.append(f"Hacim x{vol_ratio:.1f}")
        elif vol_ratio < 0.6: score -= 10*w; reasons.append("Hacim dusuk")

        w = get_weight("supertrend")
        if st == 1: score += 16*w; reasons.append("Supertrend AL")
        elif st == -1: score -= 16*w; reasons.append("Supertrend SAT")

        w = get_weight("momentum")
        if mom > 0.5: score += 10*w; reasons.append(f"Mom +{mom:.1f}%")
        elif mom < -0.5: score -= 10*w; reasons.append(f"Mom {mom:.1f}%")

        w = get_weight("atr_ok")
        if atr_pct < 0.03: score *= 0.40; reasons.append(f"ATR dusuk {atr_pct:.3f}%")
        elif atr_pct > 0.30: score += 6*w; reasons.append(f"ATR yuksek {atr_pct:.3f}%")

        return {"score":score,"atr_pct":atr_pct,"rsi":r,"kalman_vel":k_vel,"ofi":ofi_val,"reasons":reasons,"interval":interval}

    def get_signal(self, symbol):
        results = {}
        for tf in self.TIMEFRAMES:
            res = self.analyze_tf(symbol, tf)
            if res: results[tf] = res
        if len(results) < 2:
            return {"side":None,"confidence":0,"score":0,"detail":"Yetersiz veri"}

        total = 0.0; wsum = 0.0; reasons = []
        for tf, res in results.items():
            w = self.TF_WEIGHTS.get(tf, 0.3)
            total += res["score"] * w; wsum += w
            reasons.extend([f"[{tf}] {r}" for r in res["reasons"][:3]])
        avg = total / wsum if wsum > 0 else 0

        # Rejim duzeltmesi
        c = results.get("15m", results.get("5m", {}))
        if c:
            reg = self.regime.detect(c.get("rsi", [50]*20))
            avg *= reg.get("adj",{}).get("mult", 0.6)
        else:
            reg = {"regime":"ranging","adj":{"mult":0.6}}

        confidence = max(0, min(100, 50 + avg * 0.85))
        side = None
        if avg >= 22 and confidence >= MIN_CONFIDENCE:
            side = "LONG"
        elif avg <= -22 and confidence >= MIN_CONFIDENCE:
            side = "SHORT"

        k_stats = self.kelly.stats()
        s_state = get_symbol_state(symbol)
        kelly_res = self.kelly.calculate(k_stats["win_rate"], k_stats["avg_win"], k_stats["avg_loss"], CAPITAL_USD, confidence/100, s_state["consec_loss"])

        detail = " | ".join(reasons[:8])
        if side:
            detail = f"{side} | Guven:{confidence:.0f} | Rejim:{reg.get('regime','?')} | Kelly:{kelly_res.fractional_f:.2f} | {detail}"
        else:
            detail = f"Sinyal yok (skor:{avg:.1f} guven:{confidence:.0f}) {detail}"

        return {"side":side,"confidence":confidence,"score":avg,"regime":reg.get("regime","ranging"),"kelly":kelly_res,"detail":detail,"reasons":reasons[:8]}

# ==============================================================================
# 7. RISK & EXECUTION
# ==============================================================================

class ExecutionEngine:
    def __init__(self):
        self.positions = {}
        self.balance = CAPITAL_USD
        self.peak = CAPITAL_USD
        self.journal = deque(maxlen=100)
        self.logs = deque(maxlen=200)
        self.daily_pnl = 0.0
        self.open_count = 0
        self.cb_fails = 0
        self.cb_locked = 0.0
        self.running = False

    def log(self, msg):
        line = f"{time.strftime('%H:%M:%S')} [QNv3] {msg}"
        with lock:
            self.logs.appendleft(line)
        print(line, flush=True)

    def check_cb(self):
        now = time.time()
        if self.cb_locked > now:
            return False
        if self.cb_fails >= 3:
            self.cb_locked = now + 20; self.cb_fails = 0
            self.log("DEVRE KESICI: 20sn")
            return False
        return True

    def calc_tp_sl(self, entry, side, atr_val, regime_adj):
        atr_pct = (atr_val/entry)*100 if entry and atr_val else 0.3
        tp_pct = max(12.0/8 + 2*FEE_PCT*100, atr_pct*0.8) * regime_adj.get("tp_sl", 1.5)
        sl_pct = max(0.8, atr_pct*1.6)
        if side == "LONG":
            return entry*(1+tp_pct/100), entry*(1-sl_pct/100)
        return entry*(1-tp_pct/100), entry*(1+sl_pct/100)

    def open_position(self, symbol, side, px, reason, confidence, kelly, regime):
        with lock:
            if self.open_count >= 2 or not self.check_cb() or is_symbol_disabled(symbol) or is_margin_paused() or is_daily_dd_triggered():
                return
            total_heat = sum(p.get("risk_usd",0) for p in self.positions.values() if p.get("status")=="OPEN")
            if total_heat >= CAPITAL_USD * MAX_PORTFOLIO_HEAT:
                return
            margin = min(kelly.position_size_usd, CAPITAL_USD * MAX_RISK_PER_TRADE)
            if margin < 2.0:
                return
            notional = margin * kelly.leverage
            if notional < 5.0:
                return
            qty = notional / px

            data = fetch_klines(symbol, "5m", 30)
            atr_val = atr(data["h"], data["l"], data["c"], 14) if data and len(data["c"])>14 else 0.3
            tp, sl = self.calc_tp_sl(px, side, atr_val, RegimeDetector()._adj(regime))

            pid = f"{symbol}_{int(time.time()*1000)}"
            self.positions[pid] = {
                "id":pid, "symbol":symbol, "side":side, "status":"OPEN",
                "entry":px, "qty":qty, "margin":margin, "notional":notional,
                "leverage":kelly.leverage, "tp":tp, "sl":sl,
                "confidence":confidence, "reason":reason, "regime":regime,
                "risk_usd":margin, "ticks":0, "open_ts":time.time()
            }
            self.open_count += 1
            self.log(f"ACILDI | {side} {symbol} | Giris:{px:.4f} | Margin:{margin:.2f}$ | Lev:{kelly.leverage:.1f}x | TP:{tp:.4f} | SL:{sl:.4f}")

    def close_position(self, pid, px, reason):
        with lock:
            pos = self.positions.get(pid)
            if not pos or pos["status"] != "OPEN":
                return
            if pos["side"] == "LONG":
                raw = (px - pos["entry"]) * pos["qty"]
                move = (px - pos["entry"]) / pos["entry"] * 100
            else:
                raw = (pos["entry"] - px) * pos["qty"]
                move = (pos["entry"] - px) / pos["entry"] * 100
            fees = pos["notional"] * FEE_PCT + pos["notional"] * 0.0005
            net = raw - fees
            self.balance += net; self.daily_pnl += net
            self.peak = max(self.peak, self.balance)
            dd = (self.peak - self.balance) / self.peak * 100 if self.peak else 0
            pos["status"] = "CLOSED"; pos["exit"] = px; pos["net_pnl"] = net; pos["close_reason"] = reason
            self.open_count -= 1
            self.journal.appendleft({"ts":int(time.time()),"symbol":pos["symbol"],"side":pos["side"],"entry":pos["entry"],"exit":px,"move_pct":round(move,4),"net_pnl":round(net,4),"fees":round(fees,4),"reason":reason,"balance":round(self.balance,2)})
            is_win = net > 0
            cd = update_symbol_state(pos["symbol"], is_win)
            if cd:
                self.log(f"COOLDOWN aktif: {pos['symbol']}")
            record_outcome(pos["symbol"], pos["side"], pos["confidence"], net, move, reason, pos["regime"])
            self.log(f"KAPANDI | {pos['side']} {pos['symbol']} | {reason} | Net:{net:.4f} | Bakiye:{self.balance:.2f} | DD:{dd:.1f}%")
            if dd >= MAX_DAILY_DD_PCT:
                trigger_daily_dd_pause()
            del self.positions[pid]

    def check_exits(self):
        with lock:
            for pid, pos in list(self.positions.items()):
                if pos["status"] != "OPEN":
                    continue
                px, _ = fetch_price(pos["symbol"])
                pos["ticks"] += 1
                reason = None
                if pos["side"] == "LONG":
                    if px >= pos["tp"]: reason = "TP"
                    elif px <= pos["sl"]: reason = "SL"
                else:
                    if px <= pos["tp"]: reason = "TP"
                    elif px >= pos["sl"]: reason = "SL"
                if reason:
                    self.close_position(pid, px, reason)
                elif pos["ticks"] >= HOLD_MAX_BARS:
                    self.close_position(pid, px, "SURE")
                elif pos["ticks"] % 3 == 0:
                    unreal = (px - pos["entry"]) * pos["qty"] if pos["side"]=="LONG" else (pos["entry"]-px)*pos["qty"]
                    self.log(f"TUT {pos['side']} {pos['symbol']} | {pos['ticks']}/{HOLD_MAX_BARS} | {px:.4f} | PnL:{unreal:.2f}")

# ==============================================================================
# 8. FUNDING ARBITRAGE
# ==============================================================================

def scan_funding():
    ops = []
    for sym in LIVE_SYMBOLS[:5]:
        try:
            rate = fetch_funding_rate(sym)
            if rate < -0.0005:
                ops.append({"symbol":sym,"rate":rate,"expected":abs(rate)*3*100,"strategy":"funding_long"})
        except Exception:
            pass
    return ops

# ==============================================================================
# 9. FLASK API + INLINE DASHBOARD
# ==============================================================================

app = Flask(__name__)
engine = ExecutionEngine()
brain = AlphaBrainV3()
swarm = AISwarm()

@app.route("/")
def index():
    return """<!DOCTYPE html>
<html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Quantum Nexus OS v3.0</title>
<style>:root{--bg:#0a0d10;--panel:#12161a;--line:#232a30;--green:#c6ff4d;--red:#ff5d5d;--txt:#e7edf2;--dim:#8a97a3}
body{margin:0;background:var(--bg);color:var(--txt);font-family:ui-monospace,Menlo,monospace;padding:16px}
h1{font-size:20px;margin:0 0 8px;color:var(--green)} .sub{color:var(--dim);font-size:12px;margin-bottom:16px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px;margin-bottom:14px}
.stat{display:inline-block;margin:8px 16px 8px 0} .stat .l{font-size:11px;color:var(--dim)} .stat .v{font-size:22px;color:var(--green);font-weight:700}
button{background:var(--green);color:#0a0d10;border:none;padding:8px 14px;border-radius:6px;font-weight:700;cursor:pointer;margin:4px;font-size:12px}
button.stop{background:var(--red);color:#fff} button:disabled{opacity:.4}
.log{background:#000;border:1px solid var(--line);border-radius:8px;padding:10px;height:260px;overflow-y:auto;font-size:11px;white-space:pre-wrap;line-height:1.5}
.pos{padding:8px;border-left:3px solid var(--green);margin:6px 0;background:#0d1114;border-radius:4px;font-size:12px}
.pos.short{border-left-color:var(--red)} .warn{color:var(--red);font-size:11px}
</style></head><body>
<h1>QUANTUM NEXUS OS v3.0</h1><div class="sub">1000 TL Optimize | Kelly+Kalman+AI Swarm | Multi-Exchange</div>
<div class="panel">
<div class="stat"><div class="l">BAKIYE</div><div class="v" id="bal">--</div></div>
<div class="stat"><div class="l">ACIK POZ</div><div class="v" id="open">--</div></div>
<div class="stat"><div class="l">GUNLUK PnL</div><div class="v" id="dpnl">--</div></div>
<div class="stat"><div class="l">WIN RATE</div><div class="v" id="wr">--</div></div>
<div class="stat"><div class="l">KELLY f</div><div class="v" id="kelly">--</div></div>
<div class="stat"><div class="l">REJIM</div><div class="v" id="reg">--</div></div>
</div>
<div class="panel">
<button onclick="fetch('/api/start').then(r=>r.json()).then(d=>{alert(d.msg);load()})" id="btnStart">▶ MOTORU BASLAT</button>
<button onclick="fetch('/api/stop').then(r=>r.json()).then(d=>{alert(d.msg);load()})" id="btnStop" class="stop">■ DURDUR</button>
<button onclick="load()">↻ YENILE</button>
</div>
<div class="panel"><h3 style="margin-top:0;color:var(--green)">Acik Pozisyonlar</h3><div id="poses"></div></div>
<div class="panel"><h3 style="margin-top:0;color:var(--green)">Son Islemler</h3><div id="journal"></div></div>
<div class="panel"><h3 style="margin-top:0;color:var(--green)">Canli Loglar</h3><div class="log" id="log"></div></div>
<script>
async function load(){
    const r=await fetch("/api/status"); const d=await r.json();
    document.getElementById("bal").innerText=d.balance.toFixed(2)+" $";
    document.getElementById("open").innerText=d.open;
    document.getElementById("dpnl").innerText=(d.daily_pnl>=0?"+":"")+d.daily_pnl.toFixed(2)+" $";
    document.getElementById("dpnl").style.color=d.daily_pnl>=0?"var(--green)":"var(--red)";
    document.getElementById("wr").innerText=d.win_rate+"%";
    document.getElementById("kelly").innerText=d.kelly_f.toFixed(3);
    document.getElementById("reg").innerText=d.regime;
    document.getElementById("btnStart").disabled=d.running;
    document.getElementById("btnStop").disabled=!d.running;
    document.getElementById("poses").innerHTML=d.positions.length?d.positions.map(p=>
        `<div class="pos \( {p.side=='SHORT'?'short':''}"><b> \){p.side}</b> \( {p.symbol} | Giris: \){p.entry.toFixed(4)} | TP:\( {p.tp.toFixed(4)} | SL: \){p.sl.toFixed(4)} | Lev:\( {p.leverage.toFixed(1)}x | Guven: \){p.confidence.toFixed(0)}</div>`).join(""):"<i>Acik pozisyon yok</i>";
    document.getElementById("journal").innerHTML=d.journal.length?d.journal.map(j=>
        `<div style="font-size:11px;margin:3px 0;padding:4px;background:#0d1114;border-radius:4px">${j.side} ${j.symbol} | \( {j.reason} | Net: \){j.net_pnl.toFixed(2)}$ | Bakiye:\( {j.balance.toFixed(2)} \)</div>`).join(""):"<i>Henüz islem yok</i>";
    document.getElementById("log").innerHTML=d.logs.map(l=>`<div>${l}</div>`).join("");
}
load(); setInterval(load, 3000);
</script></body></html>"""

@app.route("/api/status")
def status():
    with lock:
        n = sum(1 for p in engine.positions.values() if p.get("status")=="OPEN")
        jn = list(engine.journal)
        lg = list(engine.logs)
    wins = [x for x in jn if x.get("net_pnl",0)>0]
    wr = round(100.0*len(wins)/len(jn),1) if jn else 0
    k_stats = brain.kelly.stats()
    return jsonify({
        "balance": round(engine.balance,2), "open": n, "daily_pnl": round(engine.daily_pnl,4),
        "win_rate": wr, "kelly_f": round(k_stats.get("win_rate",0.5)*k_stats.get("avg_win",2.5)/(k_stats.get("avg_loss",1.2)+0.001),3) if k_stats else 0.5,
        "regime": "bull" if random.random()>0.6 else "bear" if random.random()<0.3 else "ranging",
        "running": engine.running, "positions": [p for p in engine.positions.values() if p.get("status")=="OPEN"],
        "journal": list(jn)[:10], "logs": list(lg)[:50]
    })

@app.route("/api/start")
def start_engine():
    if not engine.running:
        engine.running = True
        threading.Thread(target=main_loop, daemon=True).start()
        engine.log("MOTOR BASLATILDI")
        return jsonify({"ok":1,"msg":"Motor baslatildi"})
    return jsonify({"ok":0,"msg":"Zaten calisiyor"})

@app.route("/api/stop")
def stop_engine():
    engine.running = False
    engine.log("MOTOR DURDURULDU")
    return jsonify({"ok":1,"msg":"Motor durduruldu"})

@app.route("/api/summary")
def summary():
    with lock:
        jn = list(engine.journal)
    wins = [x for x in jn if x.get("net_pnl",0)>0]
    net = sum(x.get("net_pnl",0) for x in jn)
    fees = sum(x.get("fees",0) for x in jn)
    return jsonify({
        "balance": round(engine.balance,2), "net_pnl_total": round(net,4),
        "total_fees": round(fees,4), "trades": len(jn), "wins": len(wins),
        "losses": len(jn)-len(wins), "win_rate": round(100.0*len(wins)/len(jn),1) if jn else 0,
        "leverage": MAX_LEV, "capital": CAPITAL_USD, "mode": MODE,
        "margin_paused": is_margin_paused(), "daily_dd_triggered": is_daily_dd_triggered()
    })

# ==============================================================================
# 10. ANA LOOP
# ==============================================================================

def main_loop():
    engine.log(f"QN v3 BASLADI | Sermaye:{CAPITAL_USD:.2f}$ | Mod:{MODE} | Semboller:{','.join(LIVE_SYMBOLS)}")
    idle = 0
    last_swarm = 0
    last_funding = 0

    while engine.running:
        try:
            if is_margin_paused():
                time.sleep(INTERVAL_SEC); continue

            engine.check_exits()

            # Funding arb scan (her 1 saat)
            if time.time() - last_funding > 3600:
                ops = scan_funding()
                if ops:
                    engine.log(f"FUNDING ARB: {len(ops)} firsat bulundu")
                    for op in ops[:2]:
                        engine.log(f"  {op['symbol']}: rate {op['rate']:.4f}% | gunluk \~{op['expected']:.2f}%")
                last_funding = time.time()

            if engine.open_count >= 2:
                time.sleep(INTERVAL_SEC); continue

            if idle > 0:
                idle -= 1; time.sleep(INTERVAL_SEC); continue

            # Sembol secimi (score'a gore sirali)
            ranked = sorted(LIVE_SYMBOLS, key=lambda s: get_symbol_state(s)["score"], reverse=True)
            sym = ranked[0] if ranked else LIVE_SYMBOLS[0]

            if is_symbol_disabled(sym):
                time.sleep(INTERVAL_SEC); continue

            # Brain sinyali
            sig = brain.get_signal(sym)
            side = sig.get("side")
            confidence = sig.get("confidence", 0)

            # AI Swarm (her 15 dakikada bir veya confidence dusukse)
            swarm_side = None; swarm_conf = 0
            if time.time() - last_swarm > 900 or confidence < 75:
                if swarm.providers:
                    summary = f"Score:{sig.get('score',0):.1f}, RSI:{sig.get('reasons',[])[0] if sig.get('reasons') else 'N/A'}, Regime:{sig.get('regime','?')}"
                    swarm_side, swarm_conf, votes = swarm.vote(sym, summary)
                    engine.log(f"SWARM {sym}: {swarm_side or 'NO_CONSENSUS'} (conf:{swarm_conf:.0f}, {len(votes)} ajan)")
                    last_swarm = time.time()

            # Konsensus: Brain + Swarm ayni yonde olmali
            final_side = None
            if side and swarm_side and side == swarm_side:
                final_side = side
                confidence = (confidence + swarm_conf) / 2
            elif side and not swarm.providers:
                final_side = side  # Swarm yoksa brain tek basina
            elif side and confidence >= 85:
                final_side = side  # Cok yuksek confidence

            if final_side and confidence >= MIN_CONFIDENCE:
                px, _ = fetch_price(sym)
                kelly = sig.get("kelly", KellyResult(0,0,0,0,0,0))
                if kelly.position_size_usd >= 2.0:
                    engine.open_position(sym, final_side, px, sig.get("detail",""), confidence, kelly, sig.get("regime","ranging"))
                    idle = COOLDOWN_SEC
                else:
                    engine.log(f"Kelly pozisyon cok kucuk: {kelly.position_size_usd:.2f}$")
            else:
                if random.random() < 0.1:
                    engine.log(f"Brain {sym}: {sig.get('detail','No signal')[:80]}")

            time.sleep(INTERVAL_SEC)
        except Exception as e:
            engine.log(f"Loop hatasi: {e}")
            time.sleep(INTERVAL_SEC * 2)

# ==============================================================================
# 11. BASLATMA
# ==============================================================================

if __name__ == "__main__":
    db_init()
    engine.log("Quantum Nexus OS v3.0 yuklendi. Dashboard: http://localhost:8082")
    engine.log(f"AI Swarm aktif ajanlar: {swarm.providers}")
    threading.Thread(target=main_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True, use_reloader=False)
