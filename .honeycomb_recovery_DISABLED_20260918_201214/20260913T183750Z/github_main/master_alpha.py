#!/data/data/com.termux/files/usr/bin/python3
# -*- coding: utf-8 -*-
"""
MASTER ALPHA CORE v1
- Multi-Horizon (1m 5m 15m 30m 1h)
- Regime Engine
- Correlation Shield
- Expectancy Guard
- Drawdown State Machine
- Anti-Martingale
- Asymmetric Exit Helpers
- Dynamic ATR Targets
Gerçek veri, mock yok.
"""

import time, json, urllib.request, sqlite3, os, math
from collections import defaultdict, deque

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "master_brain.db")
CACHE_TTL = 20

# ====================== DB ======================
def conn():
    return sqlite3.connect(DB, timeout=12)

def init():
    with conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS trades(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER, symbol TEXT, side TEXT,
            net_pnl REAL, confidence REAL, regime TEXT
        );
        CREATE TABLE IF NOT EXISTS state(
            key TEXT PRIMARY KEY, value REAL
        );
        CREATE TABLE IF NOT EXISTS weights(
            key TEXT PRIMARY KEY, value REAL
        );
        """)
        defaults = {
            "equity_peak": 0.0,
            "daily_start": 0.0,
            "risk_mult": 1.0,
            "defense_level": 0.0
        }
        for k, v in defaults.items():
            c.execute("INSERT OR IGNORE INTO state(key,value) VALUES(?,?)", (k, v))
        c.commit()

def get_state(k, default=0.0):
    with conn() as c:
        r = c.execute("SELECT value FROM state WHERE key=?", (k,)).fetchone()
        return float(r[0]) if r else default

def set_state(k, v):
    with conn() as c:
        c.execute("INSERT OR REPLACE INTO state(key,value) VALUES(?,?)", (k, float(v)))
        c.commit()

def record_trade(symbol, side, net_pnl, confidence, regime):
    with conn() as c:
        c.execute("INSERT INTO trades(ts,symbol,side,net_pnl,confidence,regime) VALUES(?,?,?,?,?,?)",
                  (int(time.time()), symbol, side, net_pnl, confidence, regime))
        c.commit()
    update_expectancy_and_risk(net_pnl)

init()

# ====================== VERİ ======================
_kmem = {}

def klines(symbol, interval="5m", limit=60):
    key = "%s_%s" % (symbol, interval)
    now = time.time()
    if key in _kmem and now - _kmem[key][0] < CACHE_TTL:
        return _kmem[key][1]
    try:
        url = "https://fapi.binance.com/fapi/v1/klines?symbol=%s&interval=%s&limit=%d" % (symbol, interval, limit)
        req = urllib.request.Request(url, headers={"User-Agent": "master-alpha"})
        with urllib.request.urlopen(req, timeout=6) as r:
            raw = json.loads(r.read().decode())
        data = {
            "c": [float(x[4]) for x in raw],
            "h": [float(x[2]) for x in raw],
            "l": [float(x[3]) for x in raw],
            "v": [float(x[5]) for x in raw]
        }
        _kmem[key] = (now, data)
        return data
    except Exception:
        return None

# ====================== İNDİKATÖRLER ======================
def ema(arr, p):
    if len(arr) < p: return None
    k = 2.0 / (p + 1)
    v = sum(arr[:p]) / p
    for x in arr[p:]:
        v = x * k + v * (1 - k)
    return v

def rsi(arr, p=14):
    if len(arr) < p + 1: return None
    g, l = [], []
    for i in range(1, len(arr)):
        d = arr[i] - arr[i-1]
        g.append(max(d, 0.0))
        l.append(max(-d, 0.0))
    ag = sum(g[-p:]) / p
    al = sum(l[-p:]) / p
    if al == 0: return 100.0
    return 100.0 - (100.0 / (1.0 + ag / al))

def atr(h, l, c, p=14):
    if len(c) < p + 1: return None
    trs = []
    for i in range(1, len(c)):
        trs.append(max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1])))
    return sum(trs[-p:]) / p

def momentum(c, p=10):
    if len(c) < p + 1: return 0.0
    return (c[-1] - c[-p-1]) / c[-p-1] * 100.0

# ====================== REJİM ======================
def detect_regime(symbol):
    d5 = klines(symbol, "5m", 50)
    d15 = klines(symbol, "15m", 40)
    if not d5 or not d15: return "UNKNOWN", 0.1

    c5, h5, l5 = d5["c"], d5["h"], d5["l"]
    c15 = d15["c"]
    a = atr(h5, l5, c5, 14)
    atr_pct = (a / c5[-1] * 100) if a and c5[-1] > 0 else 0.1

    e9 = ema(c5, 9)
    e21 = ema(c5, 21)
    e55 = ema(c15, 21) if len(c15) > 25 else None

    slope = 0.0
    if e9 and e21:
        slope = (e9 - e21) / c5[-1] * 100

    if atr_pct < 0.035:
        return "DEATH", atr_pct
    if atr_pct > 0.18:
        return "HIGHVOL", atr_pct
    if e9 and e21 and e55:
        if e9 > e21 > e55 and slope > 0.08:
            return "TREND_UP", atr_pct
        if e9 < e21 < e55 and slope < -0.08:
            return "TREND_DOWN", atr_pct
    return "RANGE", atr_pct

# ====================== MULTI-HORIZON ======================
def score_tf(symbol, interval):
    d = klines(symbol, interval, 60)
    if not d or len(d["c"]) < 30: return 0.0, {}
    c, h, l, v = d["c"], d["h"], d["l"], d["v"]
    e9 = ema(c, 9)
    e21 = ema(c, 21)
    r = rsi(c, 14)
    a = atr(h, l, c, 14)
    mom = momentum(c, 8)
    if None in (e9, e21, r, a): return 0.0, {}

    atr_pct = a / c[-1] * 100
    vol_ratio = v[-1] / (sum(v[-20:]) / 20 + 1e-9)
    s = 0.0
    detail = {}

    if e9 > e21: s += 18
    else: s -= 18
    if r > 58: s += 8
    elif r < 42: s -= 8
    if mom > 0.25: s += 10
    elif mom < -0.25: s -= 10
    if vol_ratio > 1.2: s += 7
    elif vol_ratio < 0.7: s -= 6

    detail = {"atr_pct": atr_pct, "rsi": r, "mom": mom, "vol": vol_ratio}
    return s, detail

def multi_horizon(symbol):
    tfs = [("1m", 0.12), ("5m", 0.22), ("15m", 0.28), ("30m", 0.20), ("1h", 0.18)]
    total = 0.0
    details = {}
    for tf, w in tfs:
        sc, det = score_tf(symbol, tf)
        total += sc * w
        details[tf] = det
    return total, details

# ====================== EXPECTANCY + RISK ======================
def update_expectancy_and_risk(last_pnl):
    with conn() as c:
        rows = c.execute("SELECT net_pnl FROM trades ORDER BY id DESC LIMIT 25").fetchall()
    if len(rows) < 8:
        return
    pnls = [r[0] for r in rows]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    winrate = len(wins) / len(pnls)
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = abs(sum(losses) / len(losses)) if losses else 1.0
    expectancy = (winrate * avg_win) - ((1 - winrate) * avg_loss)

    # Anti-martingale
    risk = get_state("risk_mult", 1.0)
    if last_pnl < 0:
        risk = max(0.45, risk * 0.82)
    else:
        risk = min(1.15, risk * 1.04)
    set_state("risk_mult", risk)

    # Expectancy guard
    if expectancy < -0.015:
        set_state("defense_level", 2.0)   # hard
    elif expectancy < 0.005:
        set_state("defense_level", 1.0)   # soft
    else:
        set_state("defense_level", 0.0)

def get_risk_multiplier():
    return get_state("risk_mult", 1.0)

def get_defense_level():
    return int(get_state("defense_level", 0))

# ====================== DRAWDOWN ======================
def update_equity(balance):
    peak = get_state("equity_peak", balance)
    if balance > peak:
        peak = balance
        set_state("equity_peak", peak)
    dd = (peak - balance) / peak if peak > 0 else 0.0
    if dd > 0.12:
        set_state("defense_level", 2.0)
    elif dd > 0.07:
        set_state("defense_level", max(get_state("defense_level"), 1.0))
    return dd

# ====================== KORELASYON ======================
CORR_GROUPS = [
    {"BTCUSDT", "ETHUSDT"},
    {"SOLUSDT", "AVAXUSDT", "ADAUSDT"},
    {"XRPUSDT", "DOGEUSDT"}
]

def correlation_blocked(symbol, side, open_positions):
    """open_positions: list of (symbol, side)"""
    for group in CORR_GROUPS:
        if symbol not in group:
            continue
        for pos_sym, pos_side in open_positions:
            if pos_sym in group and pos_side == side:
                return True
    return False

# ====================== ANA SİNYAL ======================
def get_master_decision(symbol, balance, open_positions):
    """
    Döner:
    {
      "allow": bool,
      "side": "LONG"/"SHORT"/None,
      "confidence": float,
      "regime": str,
      "risk_mult": float,
      "tp_atr_mult": float,
      "sl_atr_mult": float,
      "reason": str,
      "defense": int
    }
    """
    regime, atr_pct = detect_regime(symbol)
    score, details = multi_horizon(symbol)
    defense = get_defense_level()
    risk_m = get_risk_multiplier()
    dd = update_equity(balance)

    reason_parts = ["Rejim:%s" % regime, "Skor:%.1f" % score, "ATR%%:%.3f" % atr_pct]

    # Defense hard lock
    if defense >= 2:
        return {
            "allow": False, "side": None, "confidence": 0,
            "regime": regime, "risk_mult": risk_m,
            "tp_atr_mult": 1.6, "sl_atr_mult": 1.1,
            "reason": "HARD LOCK (Expectancy/Drawdown)", "defense": defense
        }

    # Death zone
    if regime == "DEATH":
        return {
            "allow": False, "side": None, "confidence": 0,
            "regime": regime, "risk_mult": risk_m * 0.5,
            "tp_atr_mult": 1.2, "sl_atr_mult": 0.9,
            "reason": "DEATH ZONE - işlem yok", "defense": defense
        }

    # Yön
    side = None
    conf = 50 + score * 0.85
    conf = max(0, min(100, conf))

    if score >= 16 and conf >= 58:
        side = "LONG"
    elif score <= -16 and conf >= 58:
        side = "SHORT"

    # Soft defense
    if defense == 1:
        risk_m *= 0.55
        conf *= 0.92
        reason_parts.append("SOFT DEFENSE")

    # Korelasyon
    if side and correlation_blocked(symbol, side, open_positions):
        return {
            "allow": False, "side": None, "confidence": conf,
            "regime": regime, "risk_mult": risk_m,
            "tp_atr_mult": 1.5, "sl_atr_mult": 1.0,
            "reason": "Korelasyon kalkanı aktif", "defense": defense
        }

    # Rejime göre TP/SL çarpanları (ATR cinsinden)
    if regime in ("TREND_UP", "TREND_DOWN"):
        tp_m, sl_m = 2.4, 1.35
    elif regime == "HIGHVOL":
        tp_m, sl_m = 1.8, 1.5
    else:  # RANGE
        tp_m, sl_m = 1.35, 0.95

    allow = side is not None and conf >= (54 if regime == "RANGE" else 57)

    reason_parts.append("Güven:%.0f" % conf)
    if side:
        reason_parts.insert(0, side)

    return {
        "allow": allow,
        "side": side,
        "confidence": conf,
        "regime": regime,
        "risk_mult": risk_m,
        "tp_atr_mult": tp_m,
        "sl_atr_mult": sl_m,
        "reason": " | ".join(reason_parts),
        "defense": defense,
        "atr_pct": atr_pct
    }

# Motor kapanışta çağırır
def on_trade_closed(symbol, side, net_pnl, confidence, regime):
    record_trade(symbol, side, net_pnl, confidence, regime)
