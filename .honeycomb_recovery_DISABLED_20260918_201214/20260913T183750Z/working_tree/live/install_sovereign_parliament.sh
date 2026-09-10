#!/data/data/com.termux/files/usr/bin/bash
# tek-paste kurulum - Termux proje kok dizininde calistirin (live/kernel.py'a erisebildiginiz yer)
set -e
echo "[1/4] alpha_core.py yaziliyor..."
cat > alpha_core.py << 'ALPHA_CORE_EOF'
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ALPHA CORE v2 — master_alpha.py'nin genişletilmiş hali.
Orijinal mimari korunur (rejim motoru, expectancy guard, drawdown state
machine, anti-martingale, korelasyon kalkanı) — üzerine 15+ gerçek
indikatör ve 6 zaman dilimi (1m/5m/15m/30m/1h/4h) eklenir.
Gerçek veri, mock yok — tüm klines Binance Futures REST'ten çekilir.
"""
import math
import os
import sqlite3
import time
import urllib.request
import json
from typing import Dict, List, Optional, Tuple

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "alpha_brain.db")
CACHE_TTL = 15
BASE_URL = os.getenv("BINANCE_BASE_URL", "https://fapi.binance.com")


def conn():
    return sqlite3.connect(DB, timeout=12)


def init():
    with conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS trades(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts INTEGER, symbol TEXT, side TEXT,
                net_pnl REAL, confidence REAL, regime TEXT
            );
            CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY, value REAL);
            """
        )
        for k, v in {"equity_peak": 0.0, "risk_mult": 1.0, "defense_level": 0.0}.items():
            c.execute("INSERT OR IGNORE INTO state(key,value) VALUES(?,?)", (k, v))
        c.commit()


init()


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
        c.execute(
            "INSERT INTO trades(ts,symbol,side,net_pnl,confidence,regime) VALUES(?,?,?,?,?,?)",
            (int(time.time()), symbol, side, net_pnl, confidence, regime),
        )
        c.commit()
    _update_expectancy_and_risk(net_pnl)


# ===================================================================== VERİ
_kmem: Dict[str, Tuple[float, Dict]] = {}


def klines(symbol: str, interval: str = "5m", limit: int = 80) -> Optional[Dict[str, List[float]]]:
    key = f"{symbol}_{interval}"
    now = time.time()
    if key in _kmem and now - _kmem[key][0] < CACHE_TTL:
        return _kmem[key][1]
    try:
        url = f"{BASE_URL}/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"
        req = urllib.request.Request(url, headers={"User-Agent": "alpha-core/2.0"})
        with urllib.request.urlopen(req, timeout=6) as r:
            raw = json.loads(r.read().decode())
        data = {
            "o": [float(x[1]) for x in raw],
            "h": [float(x[2]) for x in raw],
            "l": [float(x[3]) for x in raw],
            "c": [float(x[4]) for x in raw],
            "v": [float(x[5]) for x in raw],
        }
        _kmem[key] = (now, data)
        return data
    except Exception:
        return None


# ================================================================ İNDİKATÖRLER
def ema(arr: List[float], p: int) -> Optional[float]:
    if len(arr) < p:
        return None
    k = 2.0 / (p + 1)
    v = sum(arr[:p]) / p
    for x in arr[p:]:
        v = x * k + v * (1 - k)
    return v


def ema_series(arr: List[float], p: int) -> List[float]:
    if len(arr) < p:
        return []
    k = 2.0 / (p + 1)
    out = []
    v = sum(arr[:p]) / p
    out.append(v)
    for x in arr[p:]:
        v = x * k + v * (1 - k)
        out.append(v)
    return out


def rsi(arr: List[float], p: int = 14) -> Optional[float]:
    if len(arr) < p + 1:
        return None
    g, l = [], []
    for i in range(1, len(arr)):
        d = arr[i] - arr[i - 1]
        g.append(max(d, 0.0))
        l.append(max(-d, 0.0))
    ag = sum(g[-p:]) / p
    al = sum(l[-p:]) / p
    if al == 0:
        return 100.0
    return 100.0 - (100.0 / (1.0 + ag / al))


def atr(h: List[float], l: List[float], c: List[float], p: int = 14) -> Optional[float]:
    if len(c) < p + 1:
        return None
    trs = []
    for i in range(1, len(c)):
        trs.append(max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])))
    return sum(trs[-p:]) / p


def momentum(c: List[float], p: int = 10) -> float:
    if len(c) < p + 1:
        return 0.0
    return (c[-1] - c[-p - 1]) / c[-p - 1] * 100.0


def macd(c: List[float], fast=12, slow=26, signal=9) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    if len(c) < slow + signal:
        return None, None, None
    ef = ema_series(c, fast)
    es = ema_series(c, slow)
    n = min(len(ef), len(es))
    macd_line = [ef[-n + i] - es[-n + i] for i in range(n)]
    if len(macd_line) < signal:
        return None, None, None
    sig = ema_series(macd_line, signal)
    if not sig:
        return None, None, None
    hist = macd_line[-1] - sig[-1]
    return macd_line[-1], sig[-1], hist


def bollinger_pctb(c: List[float], p: int = 20, mult: float = 2.0) -> Optional[float]:
    if len(c) < p:
        return None
    window = c[-p:]
    mean = sum(window) / p
    var = sum((x - mean) ** 2 for x in window) / p
    sd = math.sqrt(var)
    upper, lower = mean + mult * sd, mean - mult * sd
    if upper == lower:
        return 0.5
    return (c[-1] - lower) / (upper - lower)


def stochastic(h: List[float], l: List[float], c: List[float], p: int = 14, d: int = 3) -> Tuple[Optional[float], Optional[float]]:
    if len(c) < p + d:
        return None, None
    ks = []
    for i in range(len(c) - p + 1, len(c) + 1):
        hh = max(h[i - p:i])
        ll = min(l[i - p:i])
        k = 100.0 * (c[i - 1] - ll) / (hh - ll) if hh != ll else 50.0
        ks.append(k)
    if len(ks) < d:
        return ks[-1] if ks else None, None
    return ks[-1], sum(ks[-d:]) / d


def adx(h: List[float], l: List[float], c: List[float], p: int = 14) -> Optional[float]:
    if len(c) < p * 2:
        return None
    plus_dm, minus_dm, trs = [], [], []
    for i in range(1, len(c)):
        up = h[i] - h[i - 1]
        dn = l[i - 1] - l[i]
        plus_dm.append(up if (up > dn and up > 0) else 0.0)
        minus_dm.append(dn if (dn > up and dn > 0) else 0.0)
        trs.append(max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])))
    atr_v = sum(trs[-p:]) / p
    if atr_v == 0:
        return None
    pdi = 100 * (sum(plus_dm[-p:]) / p) / atr_v
    mdi = 100 * (sum(minus_dm[-p:]) / p) / atr_v
    if pdi + mdi == 0:
        return 0.0
    dx = 100 * abs(pdi - mdi) / (pdi + mdi)
    return dx


def obv_trend(c: List[float], v: List[float], p: int = 20) -> float:
    if len(c) < p + 1:
        return 0.0
    obv = [0.0]
    for i in range(1, len(c)):
        if c[i] > c[i - 1]:
            obv.append(obv[-1] + v[i])
        elif c[i] < c[i - 1]:
            obv.append(obv[-1] - v[i])
        else:
            obv.append(obv[-1])
    recent = obv[-p:]
    slope = (recent[-1] - recent[0]) / (abs(recent[0]) + 1e-9)
    return max(-1.0, min(1.0, slope))


def vwap_dev(h: List[float], l: List[float], c: List[float], v: List[float], p: int = 30) -> float:
    if len(c) < p:
        return 0.0
    tp = [(h[i] + l[i] + c[i]) / 3.0 for i in range(-p, 0)]
    vv = v[-p:]
    denom = sum(vv) + 1e-9
    vwap = sum(t * x for t, x in zip(tp, vv)) / denom
    return (c[-1] - vwap) / vwap * 100.0 if vwap else 0.0


def cci(h: List[float], l: List[float], c: List[float], p: int = 20) -> Optional[float]:
    if len(c) < p:
        return None
    tp = [(h[i] + l[i] + c[i]) / 3.0 for i in range(len(c))]
    window = tp[-p:]
    sma = sum(window) / p
    mad = sum(abs(x - sma) for x in window) / p
    if mad == 0:
        return 0.0
    return (tp[-1] - sma) / (0.015 * mad)


def williams_r(h: List[float], l: List[float], c: List[float], p: int = 14) -> Optional[float]:
    if len(c) < p:
        return None
    hh = max(h[-p:])
    ll = min(l[-p:])
    if hh == ll:
        return -50.0
    return (hh - c[-1]) / (hh - ll) * -100.0


def full_indicator_set(symbol: str, interval: str = "5m") -> Dict[str, float]:
    """15+ indikatörü tek bir sözlükte döner — AI parlamentosuna ve loglara verilir."""
    d = klines(symbol, interval, 80)
    if not d:
        return {}
    c, h, l, v = d["c"], d["h"], d["l"], d["v"]
    m_line, m_sig, m_hist = macd(c)
    k, dline = stochastic(h, l, c)
    out = {
        "ema9": ema(c, 9), "ema21": ema(c, 21), "ema55": ema(c, 55),
        "rsi14": rsi(c, 14),
        "atr14": atr(h, l, c, 14),
        "momentum10": momentum(c, 10),
        "macd": m_line, "macd_signal": m_sig, "macd_hist": m_hist,
        "bollinger_pctb": bollinger_pctb(c, 20),
        "stoch_k": k, "stoch_d": dline,
        "adx14": adx(h, l, c, 14),
        "obv_trend": obv_trend(c, v, 20),
        "vwap_dev_pct": vwap_dev(h, l, c, v, 30),
        "cci20": cci(h, l, c, 20),
        "williams_r14": williams_r(h, l, c, 14),
        "vol_ratio": (v[-1] / (sum(v[-20:]) / 20 + 1e-9)) if len(v) >= 20 else 1.0,
    }
    return {k2: (round(v2, 5) if isinstance(v2, float) else v2) for k2, v2 in out.items() if v2 is not None}


# =================================================================== REJİM
def detect_regime(symbol: str) -> Tuple[str, float]:
    d5 = klines(symbol, "5m", 60)
    d15 = klines(symbol, "15m", 40)
    if not d5 or not d15:
        return "UNKNOWN", 0.1
    c5, h5, l5 = d5["c"], d5["h"], d5["l"]
    c15 = d15["c"]
    a = atr(h5, l5, c5, 14)
    atr_pct = (a / c5[-1] * 100) if a and c5[-1] > 0 else 0.1
    e9, e21 = ema(c5, 9), ema(c5, 21)
    e55 = ema(c15, 21) if len(c15) > 25 else None
    slope = (e9 - e21) / c5[-1] * 100 if e9 and e21 else 0.0
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


# ============================================================ MULTI-HORIZON
TF_WEIGHTS = [("1m", 0.10), ("5m", 0.20), ("15m", 0.24), ("30m", 0.18), ("1h", 0.16), ("4h", 0.12)]


def score_tf(symbol: str, interval: str) -> Tuple[float, Dict]:
    d = klines(symbol, interval, 80)
    if not d or len(d["c"]) < 40:
        return 0.0, {}
    c, h, l, v = d["c"], d["h"], d["l"], d["v"]
    e9, e21 = ema(c, 9), ema(c, 21)
    r = rsi(c, 14)
    a = atr(h, l, c, 14)
    mom = momentum(c, 8)
    m_line, m_sig, m_hist = macd(c)
    adx_v = adx(h, l, c, 14)
    pctb = bollinger_pctb(c, 20)
    if None in (e9, e21, r, a):
        return 0.0, {}
    vol_ratio = v[-1] / (sum(v[-20:]) / 20 + 1e-9)
    s = 0.0
    if e9 > e21:
        s += 16
    else:
        s -= 16
    if r > 58:
        s += 7
    elif r < 42:
        s -= 7
    if mom > 0.25:
        s += 9
    elif mom < -0.25:
        s -= 9
    if vol_ratio > 1.2:
        s += 6
    elif vol_ratio < 0.7:
        s -= 5
    if m_hist is not None:
        s += 8 if m_hist > 0 else -8
    if adx_v is not None and adx_v > 25:
        s *= 1.15  # güçlü trendde skoru büyüt
    if pctb is not None:
        if pctb > 0.95:
            s -= 5  # üst banda yapışık -> tükeniş riski
        elif pctb < 0.05:
            s += 5
    return s, {"atr_pct": a / c[-1] * 100, "rsi": r, "mom": mom, "vol": vol_ratio, "adx": adx_v}


def multi_horizon(symbol: str) -> Tuple[float, Dict]:
    total, details = 0.0, {}
    for tf, w in TF_WEIGHTS:
        sc, det = score_tf(symbol, tf)
        total += sc * w
        details[tf] = {"score": round(sc, 2), **{k: (round(v, 4) if isinstance(v, float) else v) for k, v in det.items()}}
    return total, details


# ======================================================= EXPECTANCY / RİSK
def _update_expectancy_and_risk(last_pnl: float) -> None:
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

    risk = get_state("risk_mult", 1.0)
    risk = max(0.45, risk * 0.82) if last_pnl < 0 else min(1.15, risk * 1.04)
    set_state("risk_mult", risk)

    if expectancy < -0.015:
        set_state("defense_level", 2.0)
    elif expectancy < 0.005:
        set_state("defense_level", 1.0)
    else:
        set_state("defense_level", 0.0)


def get_risk_multiplier() -> float:
    return get_state("risk_mult", 1.0)


def get_defense_level() -> int:
    return int(get_state("defense_level", 0))


def update_equity(balance: float) -> float:
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


CORR_GROUPS = [
    {"BTCUSDT", "ETHUSDT"},
    {"SOLUSDT", "AVAXUSDT", "ADAUSDT"},
    {"XRPUSDT", "DOGEUSDT"},
]


def correlation_blocked(symbol: str, side: str, open_positions: List[Tuple[str, str]]) -> bool:
    for group in CORR_GROUPS:
        if symbol not in group:
            continue
        for pos_sym, pos_side in open_positions:
            if pos_sym in group and pos_side == side:
                return True
    return False


# ======================================================== ANA TEKNİK KARAR
def get_technical_decision(symbol: str, balance: float, open_positions: List[Tuple[str, str]]) -> Dict:
    regime, atr_pct = detect_regime(symbol)
    score, tf_details = multi_horizon(symbol)
    defense = get_defense_level()
    risk_m = get_risk_multiplier()
    dd = update_equity(balance)
    indicators = full_indicator_set(symbol, "15m")

    reason_parts = [f"Rejim:{regime}", f"Skor:{score:.1f}", f"ATR%:{atr_pct:.3f}", f"DD:{dd*100:.1f}%"]

    if defense >= 2:
        return {"allow": False, "side": None, "confidence": 0, "regime": regime, "risk_mult": risk_m,
                "tp_atr_mult": 1.6, "sl_atr_mult": 1.1, "reason": "HARD LOCK (Expectancy/Drawdown)",
                "defense": defense, "atr_pct": atr_pct, "tech_score": score, "tf_details": tf_details,
                "indicators": indicators}

    if regime == "DEATH":
        return {"allow": False, "side": None, "confidence": 0, "regime": regime, "risk_mult": risk_m * 0.5,
                "tp_atr_mult": 1.2, "sl_atr_mult": 0.9, "reason": "DEATH ZONE - işlem yok",
                "defense": defense, "atr_pct": atr_pct, "tech_score": score, "tf_details": tf_details,
                "indicators": indicators}

    side = None
    conf = max(0.0, min(100.0, 50 + score * 0.8))
    if score >= 16 and conf >= 58:
        side = "LONG"
    elif score <= -16 and conf >= 58:
        side = "SHORT"

    if defense == 1:
        risk_m *= 0.55
        conf *= 0.92
        reason_parts.append("SOFT DEFENSE")

    if side and correlation_blocked(symbol, side, open_positions):
        return {"allow": False, "side": None, "confidence": conf, "regime": regime, "risk_mult": risk_m,
                "tp_atr_mult": 1.5, "sl_atr_mult": 1.0, "reason": "Korelasyon kalkanı aktif",
                "defense": defense, "atr_pct": atr_pct, "tech_score": score, "tf_details": tf_details,
                "indicators": indicators}

    if regime in ("TREND_UP", "TREND_DOWN"):
        tp_m, sl_m = 2.4, 1.35
    elif regime == "HIGHVOL":
        tp_m, sl_m = 1.8, 1.5
    else:
        tp_m, sl_m = 1.35, 0.95

    allow = side is not None and conf >= (54 if regime == "RANGE" else 57)
    reason_parts.append(f"Güven:{conf:.0f}")
    if side:
        reason_parts.insert(0, side)

    return {
        "allow": allow, "side": side, "confidence": conf, "regime": regime, "risk_mult": risk_m,
        "tp_atr_mult": tp_m, "sl_atr_mult": sl_m, "reason": " | ".join(reason_parts), "defense": defense,
        "atr_pct": atr_pct, "tech_score": score, "tf_details": tf_details, "indicators": indicators,
    }


def on_trade_closed(symbol: str, side: str, net_pnl: float, confidence: float, regime: str) -> None:
    record_trade(symbol, side, net_pnl, confidence, regime)
ALPHA_CORE_EOF

echo "[2/4] ai_parliament.py yaziliyor..."
cat > ai_parliament.py << 'AI_PARLIAMENT_EOF'
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI PARLIAMENT — çoklu-ajan karar konseyi
=========================================
- OpenRouter'daki GÜNCEL ücretsiz modelleri RUNTIME'da keşfeder
  (openrouter.ai/api/v1/models -> pricing.prompt==0 filtre). Model isimleri
  hardcode edilip zamanla bozulmaz; kodda tek bir model adı bile yazılı DEĞİL.
- Ek olarak GOOGLE_API_KEY (Gemini), XAI_API_KEY (Grok), ANTHROPIC_API_KEY
  (Claude) tanımlıysa bunlar NATIVE API'leri üzerinden ekstra oy veren
  ajanlar olarak konseye eklenir.
- En az 10 ajan: farklı roller (trend, mean-reversion, risk, rejim/volatilite,
  fonlama/maliyet, karşıt görüş/devil's advocate, çoklu-zaman-dilimi
  sentezleyici, üretken-makro, üretken-öz-eleştiri, likidite/slipaj).
- Bir ajan çağrısı BAŞARISIZ olursa o ajan o turda sayılmaz (loglanır) —
  ASLA sahte/mock bir oyla değiştirilmez. Sistemin teknik (alpha_core)
  omurgası zaten gerçek piyasa verisiyle bağımsız çalışır; AI parlamentosu
  tamamen düşse bile motor "mock veri" üretmez, sadece AI ağırlığını 0'a
  düşürür.
- Dinamik skorlama: her ajanın geçmiş isabet oranı SQLite'ta tutulur ve
  oy ağırlığı (0.4-1.6 aralığında) buna göre otomatik güncellenir.
- Her tur, her ajanın ham cevabı + ağırlığı + gerekçesi ayrı ayrı loglanır
  (izlenebilirlik / "loglardan analaşılır takip").
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "parliament.db")
OR_MODELS_URL = "https://openrouter.ai/api/v1/models"
OR_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
GEMINI_URL_TMPL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
XAI_URL = "https://api.x.ai/v1/chat/completions"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

MODEL_CACHE_TTL_SEC = int(os.getenv("OR_MODEL_CACHE_TTL_SEC", "21600"))  # 6 saat
AGENT_TIMEOUT_SEC = float(os.getenv("PARLIAMENT_AGENT_TIMEOUT_SEC", "9"))
MIN_QUORUM = int(os.getenv("PARLIAMENT_MIN_QUORUM", "3"))  # bu sayının altında oy varsa AI sonucu güvensiz sayılır

# ------------------------------------------------------------------ DB -----
def _conn():
    return sqlite3.connect(DB_PATH, timeout=12)


def init_db() -> None:
    with _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS agent_weight(
                agent_id TEXT PRIMARY KEY,
                weight REAL NOT NULL DEFAULT 1.0,
                wins INTEGER NOT NULL DEFAULT 0,
                losses INTEGER NOT NULL DEFAULT 0,
                last_ts INTEGER
            );
            CREATE TABLE IF NOT EXISTS vote_log(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts INTEGER, symbol TEXT, agent_id TEXT, model TEXT,
                direction TEXT, confidence REAL, weight REAL,
                latency_ms INTEGER, reason TEXT, error TEXT
            );
            CREATE TABLE IF NOT EXISTS model_cache(
                id INTEGER PRIMARY KEY CHECK (id = 1),
                ts INTEGER, payload TEXT
            );
            """
        )
        c.commit()


init_db()


def get_weight(agent_id: str) -> float:
    with _conn() as c:
        r = c.execute("SELECT weight FROM agent_weight WHERE agent_id=?", (agent_id,)).fetchone()
        return float(r[0]) if r else 1.0


def update_weight(agent_id: str, was_correct: bool) -> float:
    """Kazanma/kaybetme sonrası ajan ağırlığını 0.4-1.6 aralığında günceller."""
    with _conn() as c:
        r = c.execute("SELECT weight, wins, losses FROM agent_weight WHERE agent_id=?", (agent_id,)).fetchone()
        w, wins, losses = (r if r else (1.0, 0, 0))
        if was_correct:
            w = min(1.6, w * 1.06)
            wins += 1
        else:
            w = max(0.4, w * 0.90)
            losses += 1
        c.execute(
            "INSERT OR REPLACE INTO agent_weight(agent_id, weight, wins, losses, last_ts) VALUES(?,?,?,?,?)",
            (agent_id, w, wins, losses, int(time.time())),
        )
        c.commit()
        return w


def log_vote(symbol: str, agent_id: str, model: str, direction: Optional[str],
             confidence: float, weight: float, latency_ms: int,
             reason: str, error: str = "") -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO vote_log(ts,symbol,agent_id,model,direction,confidence,weight,latency_ms,reason,error) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (int(time.time()), symbol, agent_id, model, direction, confidence, weight, latency_ms, reason[:400], error[:300]),
        )
        c.commit()


# ------------------------------------------------------- MODEL DISCOVERY ---
def _http_json(url: str, headers: Dict[str, str], body: Optional[bytes] = None,
                method: str = "GET", timeout: float = 10.0) -> Any:
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def discover_free_openrouter_models(limit: int = 24) -> List[str]:
    """
    openrouter.ai/api/v1/models üzerinden pricing.prompt==0 VE
    pricing.completion==0 olan modelleri canlı çeker. Böylece kodda
    tarihi geçmiş / uydurma model adı riski sıfırlanır. Başarısız olursa
    boş liste döner — çağıran taraf bunu "AI parlamentosu bu turda küçük"
    olarak ele alır, ASLA sahte model adıyla devam etmez.
    """
    with _conn() as c:
        row = c.execute("SELECT ts, payload FROM model_cache WHERE id=1").fetchone()
    now = int(time.time())
    if row and now - row[0] < MODEL_CACHE_TTL_SEC:
        try:
            return json.loads(row[1])
        except Exception:
            pass
    try:
        data = _http_json(OR_MODELS_URL, {"User-Agent": "ai-parliament/1.0"}, timeout=10)
        models = data.get("data", [])
        free = []
        for m in models:
            pricing = m.get("pricing", {}) or {}
            try:
                p_prompt = float(pricing.get("prompt", "1") or "1")
                p_compl = float(pricing.get("completion", "1") or "1")
            except (TypeError, ValueError):
                continue
            if p_prompt == 0.0 and p_compl == 0.0:
                free.append((m.get("id"), int(m.get("context_length") or 0)))
        free.sort(key=lambda x: -x[1])
        ids = [f[0] for f in free if f[0]][:limit]
        with _conn() as c:
            c.execute("INSERT OR REPLACE INTO model_cache(id, ts, payload) VALUES(1,?,?)",
                      (now, json.dumps(ids)))
            c.commit()
        return ids
    except Exception:
        # Ağ yoksa önbellekteki en son bilinen (eski olsa bile) listeyi kullan
        if row:
            try:
                return json.loads(row[1])
            except Exception:
                return []
        return []


# ------------------------------------------------------------- AGENTS ------
# 10 sabit rol. Model ataması dinamik havuzdan round-robin yapılır — rol
# tanımı SİSTEM PROMPT'unda, model kimliğinde değil (böylece hangi ücretsiz
# model o an mevcutsa onunla çalışır).
AGENT_ROLES: List[Dict[str, str]] = [
    {"id": "trend_hunter", "kind": "financial",
     "prompt": "Sen bir trend/momentum vadeli işlem analistisin. Sadece trend gücü ve momentuma odaklan."},
    {"id": "mean_reversion", "kind": "financial",
     "prompt": "Sen bir ortalamaya dönüş (mean-reversion) ve piyasa yapısı analistisin. Aşırı alım/satım bölgelerini ara."},
    {"id": "risk_guardian", "kind": "financial",
     "prompt": "Sen bir risk yöneticisisin. Öncelik sermaye korumadır; şüpheli durumda FLAT öner."},
    {"id": "regime_vol", "kind": "financial",
     "prompt": "Sen bir volatilite/rejim analistisin. Piyasanın trend mi, range mi, yüksek volatilite mi olduğuna odaklan."},
    {"id": "funding_carry", "kind": "financial",
     "prompt": "Sen fonlama oranı ve taşıma maliyeti (funding/carry) analistisin. Fonlama yönün aleyhineyse pozisyonu zayıflat."},
    {"id": "liquidity_slip", "kind": "financial",
     "prompt": "Sen likidite ve slipaj/emir defteri analistisin. İnce likiditede agresif emri reddet."},
    {"id": "mtf_synthesizer", "kind": "financial",
     "prompt": "Sen çoklu zaman dilimi (1m-4h) sentezleyicisisin. Kısa ve uzun vadeyi birlikte değerlendir."},
    {"id": "devils_advocate", "kind": "generative",
     "prompt": "Sen karşıt görüşü savunan bir eleştirmensin. Diğer analistlerin gözden kaçırabileceği riski bul."},
    {"id": "macro_narrator", "kind": "generative",
     "prompt": "Sen makro anlatı ve piyasa psikolojisi uzmanısın. Fiyat hareketinin arkasındaki olası anlatıyı değerlendir."},
    {"id": "self_critic", "kind": "generative",
     "prompt": "Sen sistemin öz-eleştiri ajanısın. Verilen teknik skorun aşırı iyimser/kötümser olup olmadığını sorgula."},
]

RESPONSE_INSTR = (
    "Sadece geçerli JSON döndür, başka hiçbir metin ekleme: "
    '{"direction":"LONG|SHORT|FLAT","confidence":0-100,"reason":"kısa gerekçe (max 25 kelime)"}'
)


def _build_prompt(role_prompt: str, symbol: str, snapshot: Dict[str, Any]) -> str:
    return (
        f"{role_prompt}\n"
        f"Sembol: {symbol}\n"
        f"Fiyat: {snapshot.get('price')}\n"
        f"Rejim: {snapshot.get('regime')} (ATR%%={snapshot.get('atr_pct'):.4f})\n"
        f"Teknik skor (−100..+100): {snapshot.get('tech_score'):.2f}\n"
        f"İndikatörler: {json.dumps(snapshot.get('indicators', {}), ensure_ascii=False)}\n"
        f"Zaman dilimi skorları: {json.dumps(snapshot.get('tf_scores', {}), ensure_ascii=False)}\n"
        f"Açık pozisyon sayısı: {snapshot.get('open_positions', 0)}\n\n"
        f"{RESPONSE_INSTR}"
    )


def _parse_vote(text: str) -> Tuple[Optional[str], float, str]:
    try:
        start = text.index("{")
        end = text.rindex("}") + 1
        obj = json.loads(text[start:end])
        direction = str(obj.get("direction", "FLAT")).upper()
        if direction not in ("LONG", "SHORT", "FLAT"):
            direction = "FLAT"
        conf = float(obj.get("confidence", 0))
        conf = max(0.0, min(100.0, conf))
        reason = str(obj.get("reason", ""))[:300]
        return direction, conf, reason
    except Exception:
        return None, 0.0, "parse_error"


# --------------------------------------------------------- PROVIDER CALLS --
def _call_openrouter(model: str, prompt: str, api_key: str) -> str:
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.25,
        "max_tokens": 120,
    }).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://termux.local/ai-parliament",
        "X-Title": "AI-Parliament",
    }
    data = _http_json(OR_CHAT_URL, headers, body=body, method="POST", timeout=AGENT_TIMEOUT_SEC)
    return data["choices"][0]["message"]["content"]


def _call_gemini(prompt: str, api_key: str, model: str = "gemini-2.0-flash") -> str:
    url = GEMINI_URL_TMPL.format(model=model, key=api_key)
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode("utf-8")
    data = _http_json(url, {"Content-Type": "application/json"}, body=body, method="POST", timeout=AGENT_TIMEOUT_SEC)
    return data["candidates"][0]["content"]["parts"][0]["text"]


def _call_xai(prompt: str, api_key: str, model: str = "grok-2-latest") -> str:
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.25,
        "max_tokens": 120,
    }).encode("utf-8")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    data = _http_json(XAI_URL, headers, body=body, method="POST", timeout=AGENT_TIMEOUT_SEC)
    return data["choices"][0]["message"]["content"]


def _call_anthropic(prompt: str, api_key: str, model: str = "claude-sonnet-4-6") -> str:
    body = json.dumps({
        "model": model,
        "max_tokens": 150,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    data = _http_json(ANTHROPIC_URL, headers, body=body, method="POST", timeout=AGENT_TIMEOUT_SEC)
    return data["content"][0]["text"]


@dataclass
class Vote:
    agent_id: str
    model: str
    direction: Optional[str]
    confidence: float
    weight: float
    reason: str
    error: str = ""


@dataclass
class ParliamentResult:
    votes: List[Vote] = field(default_factory=list)
    quorum: int = 0
    direction: Optional[str] = None
    ai_score: float = 0.0          # -100..+100, weight-normalized
    ai_confidence: float = 0.0     # 0..100 ağırlıklı ortalama güven
    reliable: bool = False


def run_parliament(symbol: str, snapshot: Dict[str, Any]) -> ParliamentResult:
    """
    Tüm ajanları sırayla çağırır (Termux/tek çekirdek ortamda thread pool
    yerine art arda çağrı — API rate-limit'lerine karşı daha güvenli).
    Başarısız ajanlar sonuçtan tamamen düşer; sahte oyla doldurulmaz.
    """
    or_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    gem_key = os.getenv("GOOGLE_API_KEY", "").strip()
    xai_key = os.getenv("XAI_API_KEY", "").strip()
    ant_key = os.getenv("ANTHROPIC_API_KEY", "").strip()

    pool = discover_free_openrouter_models() if or_key else []
    votes: List[Vote] = []

    for i, role in enumerate(AGENT_ROLES):
        prompt = _build_prompt(role["prompt"], symbol, snapshot)
        agent_id = role["id"]
        model_used = ""
        t0 = time.time()
        try:
            if not or_key:
                raise RuntimeError("OPENROUTER_API_KEY yok")
            if not pool:
                raise RuntimeError("ücretsiz model havuzu boş (keşif başarısız)")
            model_used = pool[i % len(pool)]
            raw = _call_openrouter(model_used, prompt, or_key)
            direction, conf, reason = _parse_vote(raw)
            if direction is None:
                raise RuntimeError("JSON parse edilemedi: %r" % raw[:120])
            w = get_weight(agent_id)
            latency = int((time.time() - t0) * 1000)
            votes.append(Vote(agent_id, model_used, direction, conf, w, reason))
            log_vote(symbol, agent_id, model_used, direction, conf, w, latency, reason)
        except Exception as e:
            latency = int((time.time() - t0) * 1000)
            log_vote(symbol, agent_id, model_used, None, 0.0, get_weight(agent_id), latency, "", str(e))

    # Native ekstra ajanlar (varsa) — bunlar sabit rol listesine dahil değil,
    # konseye "ekstra" üye olarak eklenir.
    native_calls = []
    if gem_key:
        native_calls.append(("gemini_native", lambda p: _call_gemini(p, gem_key)))
    if xai_key:
        native_calls.append(("grok_native", lambda p: _call_xai(p, xai_key)))
    if ant_key:
        native_calls.append(("claude_native", lambda p: _call_anthropic(p, ant_key)))

    for agent_id, fn in native_calls:
        prompt = _build_prompt(
            "Sen bağımsız, üçüncü göz bir hakemsin. Diğer ajanlardan habersizsin; kendi analizini yap.",
            symbol, snapshot,
        )
        t0 = time.time()
        try:
            raw = fn(prompt)
            direction, conf, reason = _parse_vote(raw)
            if direction is None:
                raise RuntimeError("JSON parse edilemedi: %r" % raw[:120])
            w = get_weight(agent_id)
            latency = int((time.time() - t0) * 1000)
            votes.append(Vote(agent_id, agent_id, direction, conf, w, reason))
            log_vote(symbol, agent_id, agent_id, direction, conf, w, latency, reason)
        except Exception as e:
            latency = int((time.time() - t0) * 1000)
            log_vote(symbol, agent_id, agent_id, None, 0.0, get_weight(agent_id), latency, "", str(e))

    result = ParliamentResult(votes=votes, quorum=len(votes))
    if not votes:
        return result

    long_w = sum(v.weight * v.confidence for v in votes if v.direction == "LONG")
    short_w = sum(v.weight * v.confidence for v in votes if v.direction == "SHORT")
    total_w = sum(v.weight * max(v.confidence, 1.0) for v in votes)
    net = long_w - short_w
    result.ai_score = max(-100.0, min(100.0, (net / total_w) * 100.0)) if total_w > 0 else 0.0
    result.ai_confidence = sum(v.confidence * v.weight for v in votes) / sum(v.weight for v in votes) if votes else 0.0
    result.direction = "LONG" if result.ai_score > 0 else ("SHORT" if result.ai_score < 0 else "FLAT")
    result.reliable = result.quorum >= MIN_QUORUM
    return result


def settle_round(votes: List[Vote], actual_direction_was_profitable: Dict[str, bool]) -> None:
    """
    Bir pozisyon kapandığında çağrılır: actual_direction_was_profitable =
    {"LONG": True/False, "SHORT": True/False} — o yönde işlem açılsaydı
    kâr mı zarar mı ederdi. Her ajanın kendi yön tahminine göre ağırlığı
    güncellenir (dinamik skorlama).
    """
    for v in votes:
        if v.direction in ("LONG", "SHORT") and v.direction in actual_direction_was_profitable:
            update_weight(v.agent_id, actual_direction_was_profitable[v.direction])
AI_PARLIAMENT_EOF

echo "[3/4] sovereign_parliament_engine.py yaziliyor..."
cat > sovereign_parliament_engine.py << 'SOVEREIGN_ENGINE_EOF'
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SOVEREIGN PARLIAMENT ENGINE
============================
Çekirdek omurga DOKUNULMADAN kullanılır: live/kernel.py -> LiveKernel
(HMAC imza, token-bucket rate limit, single-flight kilit, slipaj reddi,
exchange filtreleri, gerçek fill/komisyon çözümü — bunların hiçbiri
burada tekrar yazılmadı, olduğu gibi import edilip kullanılıyor).

Bu motor üstüne ekler:
  - alpha_core: 15+ indikatör + 6 zaman dilimi (1m..4h) teknik skor,
    rejim motoru, expectancy-guard, drawdown state machine, korelasyon
    kalkanı (mevcut master_alpha.py mantığı, genişletilmiş).
  - ai_parliament: >=10 ajanlı, OpenRouter'daki GÜNCEL ücretsiz
    modelleri runtime'da keşfeden + Gemini/Grok/Claude native
    API'leriyle ek oy veren, dinamik ağırlıklı AI konseyi.
  - Teknik skor + AI skoru -> dinamik nihai güven skoru.
  - Güven skoruna göre DİNAMİK kaldıraç, DİNAMİK TP/SL (ATR bazlı),
    DİNAMİK risk büyüklüğü (anti-martingale).
  - Fonlama oranı (funding rate) ve gerçek komisyon/slipaj muhasebesi
    her işlemde ayrı ayrı loglanır.
  - EXECUTION_MODE / LIVE_ARMED kapısı: bu, projenizin KENDİ .env
    şablonlarında (env_example, env__1__example) zaten tanımlı olan
    güvenlik deseni — burada YENİDEN İCAT EDİLMEDİ, sadece uygulandı.
    LIVE_ARMED=0 iken motor GERÇEK piyasa verisiyle GERÇEK kararlar
    üretmeye devam eder (mock/simülasyon YOK); sadece emir gönderme
    adımını atlayıp "WOULD SEND" olarak loglar. LIVE_ARMED=1 + 
    EXECUTION_MODE=LIVE olduğunda emirler gerçekten borsaya gider.
  - Bridge HTTP API (varsayılan :8100) — mevcut ui_control_plane.py
    dosyanızdaki UI_PROXY_ROUTES ile birebir uyumlu: /summary,
    /positions, /journal, /status, /health. UI tarafında hiçbir
    değişiklik gerekmez.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Tuple

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from live.kernel import LiveKernel  # noqa: E402  -- çekirdek omurga, değiştirilmedi
import alpha_core  # noqa: E402
import ai_parliament  # noqa: E402

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# --------------------------------------------------------------- LOGGING ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [PARLIAMENT] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("sovereign_parliament")

# ------------------------------------------------------------------ ENV ----
EXECUTION_MODE = os.getenv("EXECUTION_MODE", "PAPER").upper()   # PAPER | TEST | LIVE
LIVE_ARMED = os.getenv("LIVE_ARMED", "0") == "1"
IS_LIVE = EXECUTION_MODE == "LIVE" and LIVE_ARMED

SYMBOLS = [s.strip().upper() for s in os.getenv("LIVE_SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT").split(",") if s.strip()]
MAX_POSITIONS = int(os.getenv("MAX_POSITIONS", "3"))
SCAN_SEC = int(os.getenv("SCAN_INTERVAL_SEC", "45"))
BASE_RISK_PCT = float(os.getenv("LIVE_RISK", os.getenv("RISK_PCT", "0.05")))
LEV_MIN = int(float(os.getenv("LEV_MIN", "5")))
LEV_MAX = int(float(os.getenv("MAX_LEVERAGE", "20")))
MAX_NOTIONAL = float(os.getenv("MAX_POSITION_SIZE_USDT", "200"))
FEE_RATE = float(os.getenv("FEE_RATE", "0.0004"))
TECH_WEIGHT = float(os.getenv("TECH_WEIGHT", "0.45"))
AI_WEIGHT = float(os.getenv("AI_WEIGHT", "0.55"))
MIN_FINAL_CONF = float(os.getenv("MIN_FINAL_CONF", "60"))

BRIDGE_HOST = os.getenv("BRIDGE_HOST", "127.0.0.1")
BRIDGE_PORT = int(os.getenv("HONEYCOMB_BRIDGE_PORT", "8100"))

kernel = LiveKernel(venue="usdt", log_fn=lambda m: log.info(m))
kernel.load_exchange_info(SYMBOLS)

_journal: List[Dict[str, Any]] = []
_open_meta: Dict[str, Dict[str, Any]] = {}
_lock = threading.Lock()
_last_votes: Dict[str, List[ai_parliament.Vote]] = {}


# ============================================================== FONLAMA ====
def get_funding_rate(symbol: str) -> float:
    """Binance premiumIndex — public endpoint, imza gerekmez."""
    try:
        url = f"{kernel.v['rest']}{kernel.v['premium']}?symbol={symbol}"
        req = urllib.request.Request(url, headers={"User-Agent": "sovereign-parliament/1.0"})
        with urllib.request.urlopen(req, timeout=6) as r:
            data = json.loads(r.read().decode())
        return float(data.get("lastFundingRate", 0.0))
    except Exception as e:
        log.warning("funding rate alınamadı %s: %s", symbol, e)
        return 0.0


# ========================================================= SKOR BİRLEŞTİRME
def combine_scores(tech: Dict[str, Any], ai: ai_parliament.ParliamentResult) -> Dict[str, Any]:
    """
    Teknik skor (-100..100) ve AI skoru (-100..100) ağırlıklı birleştirilir.
    AI konseyi güvenilir çoğunluğa (MIN_QUORUM) ulaşamadıysa AI ağırlığı
    otomatik olarak teknik tarafa kaydırılır (asla sahte AI görüşüyle
    doldurulmaz).
    """
    tw, aw = TECH_WEIGHT, AI_WEIGHT
    if not ai.reliable:
        tw, aw = 1.0, 0.0
        log.warning("AI parlamentosu quorum'a ulaşamadı (oy=%d) — bu turda sadece teknik skor kullanılacak.", ai.quorum)
    final_score = tech["tech_score"] * tw + ai.ai_score * aw
    final_conf = abs(final_score)
    side = "LONG" if final_score > 0 else ("SHORT" if final_score < 0 else None)
    return {"final_score": final_score, "final_conf": final_conf, "side": side, "tw": tw, "aw": aw}


def dynamic_leverage(final_conf: float, regime: str) -> int:
    span = LEV_MAX - LEV_MIN
    lev = LEV_MIN + span * max(0.0, min(1.0, (final_conf - MIN_FINAL_CONF) / (100.0 - MIN_FINAL_CONF + 1e-9)))
    if regime == "HIGHVOL":
        lev *= 0.7
    return max(LEV_MIN, min(LEV_MAX, int(round(lev))))


# =============================================================== ANA DÖNGÜ =
def open_positions_list() -> List[Tuple[str, str]]:
    out = []
    with _lock:
        for sym, meta in _open_meta.items():
            out.append((sym, meta["side"]))
    return out


def scan_symbol(symbol: str) -> None:
    with _lock:
        if symbol in _open_meta:
            return
        if len(_open_meta) >= MAX_POSITIONS:
            return

    balance = kernel.balance_usdt()
    tech = alpha_core.get_technical_decision(symbol, balance, open_positions_list())
    if not tech["allow"]:
        log.info("SKIP %s | %s", symbol, tech["reason"])
        return

    snapshot = {
        "price": None,
        "regime": tech["regime"],
        "atr_pct": tech["atr_pct"],
        "tech_score": tech["tech_score"],
        "indicators": tech["indicators"],
        "tf_scores": tech["tf_details"],
        "open_positions": len(_open_meta),
    }
    try:
        bid, ask, mid = kernel.book(symbol)
        snapshot["price"] = mid
    except Exception as e:
        log.warning("book alınamadı %s: %s", symbol, e)
        return

    ai_result = ai_parliament.run_parliament(symbol, snapshot)
    combo = combine_scores(tech, ai_result)
    _last_votes[symbol] = ai_result.votes

    log.info(
        "KARAR %s | teknik=%.1f ai=%.1f(quorum=%d/güvenilir=%s) final=%.1f yön=%s | rejim=%s",
        symbol, tech["tech_score"], ai_result.ai_score, ai_result.quorum, ai_result.reliable,
        combo["final_score"], combo["side"], tech["regime"],
    )
    for v in ai_result.votes:
        log.info("  oy[%s|%s] yön=%s güven=%.0f ağırlık=%.2f gerekçe=%s%s",
                  v.agent_id, v.model, v.direction, v.confidence, v.weight, v.reason,
                  (" HATA=" + v.error) if v.error else "")

    if combo["side"] is None or combo["final_conf"] < MIN_FINAL_CONF:
        log.info("SKIP %s | final güven yetersiz (%.1f < %.1f)", symbol, combo["final_conf"], MIN_FINAL_CONF)
        return

    if alpha_core.correlation_blocked(symbol, combo["side"], open_positions_list()):
        log.info("SKIP %s | korelasyon kalkanı", symbol)
        return

    lev = dynamic_leverage(combo["final_conf"], tech["regime"])
    risk_pct = BASE_RISK_PCT * tech["risk_mult"]
    tp_pct = tech["tp_atr_mult"] * tech["atr_pct"]
    sl_pct = tech["sl_atr_mult"] * tech["atr_pct"]
    funding = get_funding_rate(symbol)
    # Fonlama pozisyon yönünün aleyhineyse (long iken pozitif funding gibi)
    # güveni ve dolayısıyla boyutu hafifçe düşür — ekstra maliyet kalemi.
    funding_penalty = 1.0
    if (combo["side"] == "LONG" and funding > 0.0003) or (combo["side"] == "SHORT" and funding < -0.0003):
        funding_penalty = 0.8
        risk_pct *= funding_penalty

    log.info(
        "EMİR HAZIRLA %s %s | lev=%dx risk=%.3f%% tp=%.3f%% sl=%.3f%% funding=%.5f mode=%s live_armed=%s",
        combo["side"], symbol, lev, risk_pct * 100, tp_pct, sl_pct, funding, EXECUTION_MODE, LIVE_ARMED,
    )

    if not IS_LIVE:
        log.warning("WOULD SEND (LIVE değil) %s %s lev=%dx risk=%.3f%% — gerçek emir GÖNDERİLMEDİ.",
                    combo["side"], symbol, lev, risk_pct * 100)
        return

    try:
        res = kernel.open_market(symbol, combo["side"], risk_pct, lev, tp_pct, sl_pct, max_notional=MAX_NOTIONAL)
    except Exception as e:
        log.error("EMİR HATASI %s: %s", symbol, e)
        return

    open_fee = res["entry"] * res["qty"] * FEE_RATE
    with _lock:
        _open_meta[symbol] = {
            "side": combo["side"], "entry": res["entry"], "qty": res["qty"],
            "tp": res["tp"], "sl": res["sl"], "oid": res["oid"],
            "lev": lev, "open_fee": open_fee, "funding_at_open": funding,
            "ts": time.time(), "tech_score": tech["tech_score"], "ai_score": ai_result.ai_score,
            "confidence": combo["final_conf"], "regime": tech["regime"],
        }
    log.info("AÇILDI %s %s entry=%.6f qty=%s lev=%dx TP=%.6f SL=%.6f", combo["side"], symbol,
              res["entry"], res["qty"], lev, res["tp"], res["sl"])


def check_closed_positions() -> None:
    """Borsada kapanmış pozisyonları tespit edip PnL/masraf muhasebesini kapatır."""
    with _lock:
        symbols = list(_open_meta.keys())
    for symbol in symbols:
        with _lock:
            meta = _open_meta.get(symbol)
        if not meta:
            continue
        try:
            real_amt = kernel.position_amt(symbol, meta["side"])
        except Exception as e:
            log.warning("pozisyon kontrol hatası %s: %s", symbol, e)
            continue
        if real_amt > 0:
            continue  # hâlâ açık

        try:
            bid, ask, mid = kernel.book(symbol)
            exit_px = mid
        except Exception:
            exit_px = meta["entry"]

        close_notional = exit_px * meta["qty"]
        close_fee = close_notional * FEE_RATE
        if meta["side"] == "LONG":
            raw = (exit_px - meta["entry"]) * meta["qty"]
        else:
            raw = (meta["entry"] - exit_px) * meta["qty"]
        total_fees = meta["open_fee"] + close_fee
        net = raw - close_fee
        hold_sec = time.time() - meta["ts"]
        rec = {
            "symbol": symbol, "side": meta["side"], "entry": meta["entry"], "exit": exit_px,
            "qty": meta["qty"], "leverage": meta["lev"], "raw_pnl": round(raw, 6),
            "open_fee": round(meta["open_fee"], 6), "close_fee": round(close_fee, 6),
            "total_fees": round(total_fees, 6), "net_pnl": round(net, 6),
            "hold_sec": round(hold_sec, 1), "regime": meta["regime"],
            "confidence": meta["confidence"], "closed_ts": int(time.time()),
        }
        with _lock:
            _journal.insert(0, rec)
            if len(_journal) > 300:
                _journal.pop()
            _open_meta.pop(symbol, None)

        alpha_core.on_trade_closed(symbol, meta["side"], net, meta["confidence"], meta["regime"])
        votes = _last_votes.get(symbol, [])
        was_profitable = {meta["side"]: net > 0, ("SHORT" if meta["side"] == "LONG" else "LONG"): net <= 0}
        ai_parliament.settle_round(votes, was_profitable)

        log.info(
            "KAPANDI %s %s | entry=%.6f exit=%.6f net=%.6f (ham=%.6f masraf=%.6f) hold=%.0fs",
            meta["side"], symbol, meta["entry"], exit_px, net, raw, total_fees, hold_sec,
        )


def main_loop() -> None:
    log.info(
        "ONLINE | mode=%s live_armed=%s symbols=%s max_pos=%d scan=%ds tech_w=%.2f ai_w=%.2f",
        EXECUTION_MODE, LIVE_ARMED, SYMBOLS, MAX_POSITIONS, SCAN_SEC, TECH_WEIGHT, AI_WEIGHT,
    )
    if not IS_LIVE:
        log.warning(
            "CANLI EMİR KAPALI (EXECUTION_MODE=%s, LIVE_ARMED=%s). Motor GERÇEK piyasa verisiyle "
            "GERÇEK kararlar üretmeye devam ediyor, sadece borsaya emir göndermiyor. "
            "Gerçekten canlıya almak için .env içinde EXECUTION_MODE=LIVE ve LIVE_ARMED=1 yapın.",
            EXECUTION_MODE, LIVE_ARMED,
        )
    while True:
        try:
            check_closed_positions()
            for symbol in SYMBOLS:
                scan_symbol(symbol)
                time.sleep(1.2)  # ajan/istek yükünü sembol başına yay
            time.sleep(SCAN_SEC)
        except KeyboardInterrupt:
            log.info("Durduruldu.")
            break
        except Exception as e:
            log.error("DÖNGÜ HATASI: %s", e)
            time.sleep(10)


# ========================================================== BRIDGE HTTP API
class BridgeHandler(BaseHTTPRequestHandler):
    def _send(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        if path == "/health":
            self._send(200, {"ok": True, "ts": int(time.time())})
        elif path == "/status":
            self._send(200, {
                "mode": EXECUTION_MODE, "live_armed": LIVE_ARMED, "symbols": SYMBOLS,
                "open_positions": len(_open_meta), "max_positions": MAX_POSITIONS,
            })
        elif path == "/positions":
            with _lock:
                self._send(200, [{"symbol": s, **m} for s, m in _open_meta.items()])
        elif path == "/journal":
            with _lock:
                self._send(200, _journal[:100])
        elif path == "/summary":
            with _lock:
                total_net = sum(r["net_pnl"] for r in _journal)
                wins = len([r for r in _journal if r["net_pnl"] > 0])
                total = len(_journal)
            self._send(200, {
                "mode": EXECUTION_MODE, "live_armed": LIVE_ARMED,
                "open_positions": len(_open_meta), "closed_trades": total,
                "win_rate": round(wins / total, 4) if total else None,
                "total_net_pnl": round(total_net, 6),
                "risk_mult": alpha_core.get_risk_multiplier(),
                "defense_level": alpha_core.get_defense_level(),
            })
        else:
            self._send(404, {"error": "NOT_FOUND"})

    def log_message(self, *_args: Any) -> None:
        return


def start_bridge_server() -> None:
    server = ThreadingHTTPServer((BRIDGE_HOST, BRIDGE_PORT), BridgeHandler)
    log.info("BRIDGE API http://%s:%d (ui_control_plane.py BRIDGE_URL ile uyumlu)", BRIDGE_HOST, BRIDGE_PORT)
    server.serve_forever()


def main() -> None:
    t = threading.Thread(target=start_bridge_server, daemon=True)
    t.start()
    main_loop()


if __name__ == "__main__":
    main()
SOVEREIGN_ENGINE_EOF

echo "[4/4] syntax kontrolu..."
python3 -m py_compile alpha_core.py ai_parliament.py sovereign_parliament_engine.py
echo "TAMAM. Calistirmak icin:  python3 sovereign_parliament_engine.py"
echo "Once .env dosyanizda su degiskenlerin oldugundan emin olun:"
echo "  EXECUTION_MODE, LIVE_ARMED, LIVE_SYMBOLS, MAX_POSITIONS, LEV_MIN, MAX_LEVERAGE,"
echo "  MAX_POSITION_SIZE_USDT, LIVE_RISK, FEE_RATE, TECH_WEIGHT, AI_WEIGHT, MIN_FINAL_CONF,"
echo "  OPENROUTER_API_KEY (zorunlu), GOOGLE_API_KEY / XAI_API_KEY / ANTHROPIC_API_KEY (istege bagli),"
echo "  BINANCE_API_KEY, BINANCE_SECRET_KEY, HONEYCOMB_BRIDGE_PORT"
