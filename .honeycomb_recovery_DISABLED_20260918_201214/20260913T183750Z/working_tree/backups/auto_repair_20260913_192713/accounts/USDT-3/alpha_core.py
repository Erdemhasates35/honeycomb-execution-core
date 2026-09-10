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
TF_WEIGHTS = [("1m", 0.07), ("3m", 0.07), ("5m", 0.17), ("15m", 0.20), ("30m", 0.15), ("1h", 0.14), ("2h", 0.10), ("4h", 0.10)]


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


# ================================================================= MAKRO ===
def macro_bias(symbol: str) -> Tuple[int, str]:
    """
    Uzun vade filtre: 1 günlük ve 1 haftalık mumlarla makro trend yönünü
    belirler. Döndürür: (yön: 1=yukarı, -1=aşağı, 0=karışık/nötr, açıklama).

    NOT (dürüstlük): Binance Futures'ta "1 yıllık mum" diye bir interval
    YOKTUR (en uzun native interval 1M/aylık). Bu yüzden "1 yıla kadar
    geriye dönük" isteği burada en uzun anlamlı interval olan 1w
    (haftalık) ile karşılanıyor — olmayan bir veri kaynağını varmış gibi
    göstermek yerine gerçek en uzun interval kullanılıyor ve bu açıkça
    belirtiliyor.
    """
    d1 = klines(symbol, "1d", 60)
    w1 = klines(symbol, "1w", 40)
    if not d1 or not w1 or len(d1["c"]) < 25 or len(w1["c"]) < 12:
        return 0, "makro veri yetersiz (nötr)"
    e_d_fast, e_d_slow = ema(d1["c"], 9), ema(d1["c"], 21)
    e_w_fast, e_w_slow = ema(w1["c"], 5), ema(w1["c"], 10)
    if None in (e_d_fast, e_d_slow, e_w_fast, e_w_slow):
        return 0, "makro veri yetersiz (nötr)"
    daily_up = e_d_fast > e_d_slow
    weekly_up = e_w_fast > e_w_slow
    if daily_up and weekly_up:
        return 1, "makro yukarı uyumlu (günlük+haftalık)"
    if (not daily_up) and (not weekly_up):
        return -1, "makro aşağı uyumlu (günlük+haftalık)"
    return 0, "makro karışık (günlük/haftalık uyuşmuyor)"


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
        _arm_defense(2.0)
    elif expectancy < 0.005:
        _arm_defense(1.0)
    else:
        set_state("defense_level", 0.0)
        set_state("defense_until", 0.0)


def get_risk_multiplier() -> float:
    return get_state("risk_mult", 1.0)


DEFENSE_COOLDOWN_SEC = int(os.getenv("DEFENSE_COOLDOWN_SEC", "1800"))  # 30 dk
EQUITY_MIN_INTERVAL_SEC = int(os.getenv("EQUITY_MIN_INTERVAL_SEC", "20"))


def get_defense_level() -> int:
    """
    ÖNEMLİ DÜZELTME: eskiden bir kere HARD LOCK (defense=2) tetiklenince,
    kilit yalnızca kapanan bir işlemden sonra expectancy yeniden
    hesaplanınca açılıyordu. Ama kilitliyken zaten işlem açılmadığı için
    hiçbir işlem kapanmıyor ve kilit SONSUZA KADAR açılmıyordu (canlı
    testte gördüğünüz "her sembolde HARD LOCK" tıkanıklığının sebebi
    tam olarak buydu). Artık her kilidin bir süresi var: süre dolunca
    kilit otomatik kalkıyor, sistem tekrar karar üretmeye başlıyor.
    """
    until = get_state("defense_until", 0)
    if until and time.time() >= until:
        set_state("defense_level", 0.0)
        set_state("defense_until", 0.0)
        return 0
    return int(get_state("defense_level", 0))


def get_defense_remaining_sec() -> int:
    until = get_state("defense_until", 0)
    return max(0, int(until - time.time())) if until else 0


def _arm_defense(level: float) -> None:
    current = get_state("defense_level", 0.0)
    if level > current:
        set_state("defense_level", level)
    set_state("defense_until", time.time() + DEFENSE_COOLDOWN_SEC)


def update_equity(equity: float) -> float:
    """
    equity: HESABIN GERÇEK CÜZDAN BAKİYESİ (wallet/margin balance) olmalı —
    availableBalance (kullanılabilir/boş marj) DEĞİL. availableBalance,
    hesapta çalışan BAŞKA botların/pozisyonların marj kullanımına göre
    dakikalar içinde %10-15 oynayabilir; bu, gerçek bir zarar olmadığı
    halde sahte "drawdown" alarmı üretir (canlı testte gördüğünüz
    DD:%11.8, DD:%14.2'nin sebebi buydu). Doğru equity kaynağı için
    sovereign_parliament_engine.py'deki get_wallet_equity() kullanılıyor.

    Ayrıca gürültüyü azaltmak için tepe/DD hesaplaması en fazla
    EQUITY_MIN_INTERVAL_SEC'de bir güncellenir (döngüde her sembol için
    ayrı ayrı değil, pratikte tur başına ~1 kez).
    """
    last_ts = get_state("equity_last_ts", 0)
    now = time.time()
    if now - last_ts < EQUITY_MIN_INTERVAL_SEC:
        return get_state("last_dd", 0.0)
    set_state("equity_last_ts", now)

    peak = get_state("equity_peak", equity)
    if equity > peak or peak <= 0:
        peak = equity
        set_state("equity_peak", peak)
    dd = (peak - equity) / peak if peak > 0 else 0.0
    set_state("last_dd", dd)
    if dd > 0.12:
        _arm_defense(2.0)
    elif dd > 0.07:
        _arm_defense(1.0)
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
    macro_dir, macro_label = macro_bias(symbol)
    # Kısa vadeli skor makro trendle aynı yöndeyse güçlendir, ters yöndeyse
    # zayıflat (tamamen iptal etme — geçerli kısa vadeli dönüşleri de kapatmasın).
    score_sign = 1 if score > 0 else (-1 if score < 0 else 0)
    if macro_dir != 0 and score_sign != 0:
        score *= 1.18 if score_sign == macro_dir else 0.62
    defense = get_defense_level()
    risk_m = get_risk_multiplier()
    dd = update_equity(balance)
    indicators = full_indicator_set(symbol, "15m")

    reason_parts = [f"Rejim:{regime}", f"Skor:{score:.1f}", f"ATR%:{atr_pct:.3f}", f"DD:{dd*100:.1f}%", macro_label]

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
        "macro_dir": macro_dir, "macro_label": macro_label,
    }


def on_trade_closed(symbol: str, side: str, net_pnl: float, confidence: float, regime: str) -> None:
    record_trade(symbol, side, net_pnl, confidence, regime)
