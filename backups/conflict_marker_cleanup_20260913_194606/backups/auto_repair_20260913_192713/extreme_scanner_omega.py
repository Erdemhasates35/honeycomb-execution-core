#!/usr/bin/env python3
# -*- coding: utf-8 -*-
<<<<<<< HEAD
"""
HONEYCOMB EXTREME SCANNER OMEGA
LIVE tactical reversal engine.

Omurga:
  LiveKernel
  DynamicTrailingStopEngine
  PartialProfitEngine
  CircuitBreaker
  CryptographicAuditLedger
  alpha_core

Katmanlar:
  L1 market/indicator perception
  L2 deterministic score + regime + MTF + cost/EV
  L3 execution + position management

Not:
  Skor olasılık garantisi değildir; gerçekleşen sonuçlar audit/journal ile ölçülür.
"""

from __future__ import annotations

import html
import json
import logging
import math
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from statistics import median
from typing import Any, Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from live.kernel import (
    LiveKernel,
    DynamicTrailingStopEngine,
    PartialProfitEngine,
    CircuitBreaker,
    CryptographicAuditLedger,
    load_env,
)
import alpha_core


# ============================================================ ENV

try:
    for _k, _v in load_env().items():
        os.environ.setdefault(_k, _v)
except Exception as _e:
    print("UYARI .env: %s" % _e, flush=True)

ACCOUNT_LABEL = os.getenv("ACCOUNT_LABEL", "SCANNER-OMEGA")

logging.basicConfig(
    level=logging.INFO,
    format=f"%(asctime)s [%(levelname)s] [OMEGA:{ACCOUNT_LABEL}] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("extreme_scanner_omega")

# LIVE ONLY
EXECUTION_MODE = os.getenv("EXECUTION_MODE", "LIVE").upper()
if EXECUTION_MODE != "LIVE":
    log.warning("EXECUTION_MODE=%s -> motor yalnız LIVE moduna izin verir.", EXECUTION_MODE)

VENUE = os.getenv("VENUE", "usdt").lower()

DEFAULT_WIDE_SYMBOLS = (
    "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,ADAUSDT,DOGEUSDT,"
    "AVAXUSDT,LINKUSDT,LTCUSDT,DOTUSDT,MATICUSDT,TRXUSDT,ATOMUSDT,"
    "NEARUSDT,APTUSDT,ARBUSDT,OPUSDT,FILUSDT,ETCUSDT,UNIUSDT,"
    "ICPUSDT,SUIUSDT,INJUSDT"
)

WIDE_SYMBOLS = [
    s.strip().upper()
    for s in os.getenv("WIDE_SYMBOLS", DEFAULT_WIDE_SYMBOLS).split(",")
    if s.strip()
]

MAX_POSITIONS = int(os.getenv("SCANNER_MAX_POSITIONS", "8"))
SCAN_INTERVAL_SEC = float(os.getenv("SCANNER_INTERVAL_SEC", "12"))
SYMBOL_DELAY_SEC = float(os.getenv("SCANNER_SYMBOL_DELAY_SEC", "0.35"))

# MTF
TIMEFRAMES = [
    x.strip()
    for x in os.getenv("SCANNER_TIMEFRAMES", "1m,5m,15m,1h").split(",")
    if x.strip()
]

# Core threshold
REVERSION_THRESHOLD = float(os.getenv("REVERSION_THRESHOLD", "66"))
OMEGA_ENTRY_SCORE = float(os.getenv("OMEGA_ENTRY_SCORE", "74"))
OMEGA_STRONG_SCORE = float(os.getenv("OMEGA_STRONG_SCORE", "84"))

# Risk / sizing
BASE_RISK_PCT = float(os.getenv("SCANNER_RISK", "0.015"))
MIN_RISK_PCT = float(os.getenv("SCANNER_MIN_RISK", "0.004"))
MAX_RISK_PCT = float(os.getenv("SCANNER_MAX_RISK", "0.025"))

LEV_MIN = int(float(os.getenv("LEV_MIN", "10")))
LEV_MAX = int(float(os.getenv("MAX_LEVERAGE", "50")))

MAX_NOTIONAL = float(os.getenv("MAX_POSITION_SIZE_USDT", "500"))
PORTFOLIO_MULTIPLIER = float(os.getenv("SCANNER_PORTFOLIO_MULTIPLIER", "2.5"))

FEE_RATE = float(os.getenv("FEE_RATE", "0.0004"))
SLIPPAGE_BPS = float(os.getenv("SCANNER_SLIPPAGE_BPS", "2.0"))
FUNDING_RESERVE_PCT = float(os.getenv("SCANNER_FUNDING_RESERVE", "0.0002"))

# Extreme conditions
RSI_LOW = float(os.getenv("SCANNER_RSI_LOW", "25"))
RSI_HIGH = float(os.getenv("SCANNER_RSI_HIGH", "75"))
BAND_EXTREME = float(os.getenv("SCANNER_BAND_EXTREME", "0.97"))

# Liquidity
MAX_SPREAD_BPS = float(os.getenv("SCANNER_MAX_SPREAD_BPS", "12"))
STALE_QUOTE_SEC = float(os.getenv("SCANNER_STALE_QUOTE_SEC", "3"))

# Tactical timing
MAX_HOLD_SEC = float(os.getenv("SCANNER_MAX_HOLD_SEC", "1800"))
MIN_TP_PCT = float(os.getenv("SCANNER_MIN_TP_PCT", "0.20"))
MIN_SL_PCT = float(os.getenv("SCANNER_MIN_SL_PCT", "0.30"))

BRIDGE_HOST = os.getenv("BRIDGE_HOST", "127.0.0.1")
BRIDGE_PORT = int(os.getenv("HONEYCOMB_SCANNER_PORT", "8200"))

AUDIT_FILE = os.path.join(
    ROOT,
    os.getenv("SCANNER_AUDIT_FILE", "scanner_omega_audit.jsonl"),
)


# ============================================================ STATE

kernel = LiveKernel(
    venue=VENUE,
    log_fn=lambda m: log.info(m),
)

kernel.load_exchange_info(WIDE_SYMBOLS)

trail_engine = DynamicTrailingStopEngine(
    kernel,
    log_fn=lambda m: log.info(m),
)

partial_engine = PartialProfitEngine(
    kernel,
    log_fn=lambda m: log.info(m),
)

order_breaker = CircuitBreaker(
    fail_threshold=4,
    cooldown_sec=180,
)

audit = CryptographicAuditLedger(AUDIT_FILE)

_lock = threading.RLock()
_runtime_lock = threading.RLock()

_open_meta: Dict[str, Dict[str, Any]] = {}
_journal: List[Dict[str, Any]] = []
_decision_log: List[Dict[str, Any]] = []
_signal_book: Dict[str, Dict[str, Any]] = {}

RUNTIME = {
    "live_armed": os.getenv("LIVE_ARMED", "0") == "1",
    "cycle": 0,
    "started": time.time(),
}


# ============================================================ UTILS

def finite(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
        return v if math.isfinite(v) else default
    except Exception:
        return default


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def pct_distance(a: float, b: float) -> float:
    if b == 0:
        return 0.0
    return abs(a - b) / abs(b) * 100.0


def safe_get(d: Any, *keys: str, default: Any = None) -> Any:
    if not isinstance(d, dict):
        return default
    for key in keys:
        if key in d and d[key] is not None:
            return d[key]
    return default


def num(d: Any, *keys: str, default: float = 0.0) -> float:
    return finite(safe_get(d, *keys, default=default), default)


def rset(key: str, value: Any) -> None:
    with _runtime_lock:
        RUNTIME[key] = value


def rget(key: str) -> Any:
    with _runtime_lock:
        return RUNTIME.get(key)


def is_live() -> bool:
    with _runtime_lock:
        return EXECUTION_MODE == "LIVE" and bool(RUNTIME["live_armed"])


# ============================================================ WALLET

def get_wallet_equity() -> float:
    try:
        data = kernel._http(
            "GET",
            kernel.v["balance"],
            {},
            signed=True,
            weight=5,
        )

        if isinstance(data, list):
            for a in data:
                if a.get("asset") == "USDT":
                    return max(
                        0.0,
                        num(
                            a,
                            "availableBalance",
                            "crossWalletBalance",
                            "balance",
                            default=0,
                        ),
                    )
    except Exception as e:
        log.warning("wallet equity fallback: %s", e)

    try:
        return max(0.0, finite(kernel.balance_usdt()))
    except Exception:
        return 0.0


def portfolio_notional_blocked(
    new_notional: float,
    equity: float,
    max_mult: float = PORTFOLIO_MULTIPLIER,
) -> bool:

    if equity <= 0:
        return True

    with _lock:
        current = sum(
            finite(m.get("entry"))
            * finite(m.get("qty"))
            * max(1.0, finite(m.get("lev"), 1.0))
            for m in _open_meta.values()
        )

    return current + new_notional > equity * max_mult


# ============================================================ INDICATOR EXTRACTION

def indicator_value(ind: Dict[str, Any], *names: str) -> Optional[float]:
    for name in names:
        if name in ind and ind[name] is not None:
            try:
                return float(ind[name])
            except Exception:
                pass

    # Case-insensitive fallback
    lowered = {str(k).lower(): v for k, v in ind.items()}
    for name in names:
        v = lowered.get(name.lower())
        if v is not None:
            try:
                return float(v)
            except Exception:
                pass

    return None


def normalize_indicator(ind: Dict[str, Any]) -> Dict[str, float]:
    return {
        "rsi": finite(indicator_value(ind, "rsi", "RSI"), 50),
        "stoch": finite(
            indicator_value(
                ind,
                "stoch",
                "stoch_k",
                "stochK",
                "stochastic",
            ),
            50,
        ),
        "williams": finite(
            indicator_value(
                ind,
                "williams_r",
                "williams",
                "willr",
                "WilliamsR",
            ),
            -50,
        ),
        "cci": finite(
            indicator_value(ind, "cci", "CCI"),
            0,
        ),
        "mfi": finite(
            indicator_value(ind, "mfi", "MFI"),
            50,
        ),
        "bb_position": finite(
            indicator_value(
                ind,
                "bb_position",
                "bollinger_position",
                "bb_pos",
            ),
            0.5,
        ),
        "atr_pct": finite(
            indicator_value(
                ind,
                "atr_pct",
                "ATR_pct",
                "atrPercent",
            ),
            0,
        ),
        "adx": finite(
            indicator_value(ind, "adx", "ADX"),
            0,
        ),
        "close": finite(
            indicator_value(
                ind,
                "close",
                "price",
                "last",
                "mark",
            ),
            0,
        ),
        "ema_fast": finite(
            indicator_value(
                ind,
                "ema_fast",
                "ema9",
                "ema_9",
                "EMA9",
            ),
            0,
        ),
        "ema_slow": finite(
            indicator_value(
                ind,
                "ema_slow",
                "ema21",
                "ema_21",
                "EMA21",
            ),
            0,
        ),
    }


# ============================================================ EXTREME SCORE

def oscillator_components(
    x: Dict[str, float],
) -> Tuple[float, float, Dict[str, float]]:

    rsi = x["rsi"]
    stoch = x["stoch"]
    will = x["williams"]
    cci = x["cci"]
    mfi = x["mfi"]
    bb = x["bb_position"]

    long_votes = 0
    short_votes = 0

    if rsi <= RSI_LOW:
        long_votes += 1
    elif rsi >= RSI_HIGH:
        short_votes += 1

    if stoch <= 20:
        long_votes += 1
    elif stoch >= 80:
        short_votes += 1

    if will <= -80:
        long_votes += 1
    elif will >= -20:
        short_votes += 1

    if cci <= -100:
        long_votes += 1
    elif cci >= 100:
        short_votes += 1

    if mfi <= 20:
        long_votes += 1
    elif mfi >= 80:
        short_votes += 1

    if bb <= 0.05:
        long_votes += 1
    elif bb >= 0.95:
        short_votes += 1

    total = max(1, long_votes + short_votes)

    long_strength = long_votes / 6.0 * 100.0
    short_strength = short_votes / 6.0 * 100.0

    return (
        long_strength,
        short_strength,
        {
            "rsi": rsi,
            "stoch": stoch,
            "williams": will,
            "cci": cci,
            "mfi": mfi,
            "bb_position": bb,
            "long_votes": float(long_votes),
            "short_votes": float(short_votes),
        },
    )


def extreme_quality(
    indicators: Dict[str, Any],
    rev_score: float,
) -> Dict[str, Any]:

    x = normalize_indicator(indicators)

    long_o, short_o, osc = oscillator_components(x)

    direction = 1 if rev_score > 0 else -1

    oscillator_score = long_o if direction > 0 else short_o

    # Bollinger extremity
    if direction > 0:
        band_score = clamp((0.50 - x["bb_position"]) * 200.0, 0, 100)
    else:
        band_score = clamp((x["bb_position"] - 0.50) * 200.0, 0, 100)

    # RSI extremity
    if direction > 0:
        rsi_score = clamp((50.0 - x["rsi"]) * 2.0, 0, 100)
    else:
        rsi_score = clamp((x["rsi"] - 50.0) * 2.0, 0, 100)

    # EMA structure = confirmation, not primary reversal signal
    if x["ema_fast"] and x["ema_slow"]:
        ema_gap = (x["ema_fast"] - x["ema_slow"]) / max(
            abs(x["ema_slow"]),
            1e-12,
        ) * 100.0

        ema_confirmation = (
            clamp((-ema_gap) * 15.0, 0, 100)
            if direction > 0
            else clamp(ema_gap * 15.0, 0, 100)
        )
    else:
        ema_confirmation = 50.0

    # Core reversal score normalized to 0..100
    core_score = clamp(abs(rev_score), 0, 100)

    # Deterministic weighted score
    final_score = (
        core_score * 0.34
        + oscillator_score * 0.26
        + band_score * 0.14
        + rsi_score * 0.10
        + ema_confirmation * 0.06
        + 50.0 * 0.10
    )

    final_score = clamp(final_score, 0, 100)

    return {
        "score": round(final_score, 2),
        "core": round(core_score, 2),
        "oscillator": round(oscillator_score, 2),
        "band": round(band_score, 2),
        "rsi_extreme": round(rsi_score, 2),
        "ema_confirmation": round(ema_confirmation, 2),
        "osc": osc,
        "x": x,
    }


# ============================================================ MTF

def collect_mtf(symbol: str) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}

    for tf in TIMEFRAMES:
        try:
            raw = alpha_core.full_indicator_set(symbol, tf)
            if raw:
                out[tf] = normalize_indicator(raw)
        except Exception as e:
            log.debug("MTF %s %s: %s", symbol, tf, e)

    return out


def mtf_alignment(
    mtf: Dict[str, Dict[str, Any]],
    side: str,
) -> Tuple[float, str]:

    if not mtf:
        return 50.0, "MTF veri yok"

    votes = []
    for tf, x in mtf.items():
        rsi = x["rsi"]
        bb = x["bb_position"]

        if side == "LONG":
            vote = (
                rsi <= 45
                or bb <= 0.30
                or (
                    x["ema_fast"]
                    and x["ema_slow"]
                    and x["ema_fast"] > x["ema_slow"]
                )
            )
        else:
            vote = (
                rsi >= 55
                or bb >= 0.70
                or (
                    x["ema_fast"]
                    and x["ema_slow"]
                    and x["ema_fast"] < x["ema_slow"]
                )
            )

        votes.append(1 if vote else 0)

    alignment = sum(votes) / len(votes) * 100.0

    return alignment, f"{sum(votes)}/{len(votes)} TF uyumu"


# ============================================================ MICROSTRUCTURE

def get_book(symbol: str) -> Dict[str, float]:
    try:
        bid, ask, mid = kernel.book(symbol)

        bid = finite(bid)
        ask = finite(ask)
        mid = finite(mid)

        if mid <= 0:
            mid = (bid + ask) / 2.0 if bid > 0 and ask > 0 else 0.0

        spread_bps = (
            abs(ask - bid) / mid * 10000.0
            if mid > 0 and ask >= bid > 0
            else 9999.0
        )

        return {
            "bid": bid,
            "ask": ask,
            "mid": mid,
            "spread_bps": spread_bps,
            "ts": time.time(),
        }

    except Exception:
        return {
            "bid": 0.0,
            "ask": 0.0,
            "mid": 0.0,
            "spread_bps": 9999.0,
            "ts": time.time(),
        }


def liquidity_score(book: Dict[str, float]) -> float:
    spread = finite(book.get("spread_bps"), 9999)
    if spread >= MAX_SPREAD_BPS:
        return 0.0

    return clamp(
        100.0 * (1.0 - spread / MAX_SPREAD_BPS),
        0,
        100,
    )


# ============================================================ COST / EV

def transaction_cost_pct() -> float:
    return (
        FEE_RATE * 2.0 * 100.0
        + SLIPPAGE_BPS / 100.0
        + FUNDING_RESERVE_PCT * 100.0
    )


def expected_edge(
    score: float,
    tp_pct: float,
    sl_pct: float,
) -> Dict[str, float]:

    # Score -> model confidence, deliberately bounded.
    p_win = clamp(
        0.45 + (score - 50.0) / 250.0,
        0.45,
        0.82,
    )

    p_loss = 1.0 - p_win

    gross_expectancy = (
        p_win * tp_pct
        - p_loss * sl_pct
    )

    cost = transaction_cost_pct()
    net_expectancy = gross_expectancy - cost

    return {
        "p_win_model": round(p_win, 5),
        "p_loss_model": round(p_loss, 5),
        "gross_ev_pct": round(gross_expectancy, 5),
        "cost_pct": round(cost, 5),
        "net_ev_pct": round(net_expectancy, 5),
    }


# ============================================================ DYNAMIC RISK

def dynamic_risk(score: float, regime: str, atr_pct: float) -> float:
    quality = clamp((score - OMEGA_ENTRY_SCORE) / 26.0, 0, 1)

    risk = BASE_RISK_PCT * (
        0.70
        + quality * 0.70
    )

    if regime in ("HIGH_VOL", "DEATH"):
        risk *= 0.55

    if atr_pct > 3.0:
        risk *= 0.70
    elif atr_pct > 2.0:
        risk *= 0.85

    try:
        risk *= finite(alpha_core.get_risk_multiplier(), 1.0)
    except Exception:
        pass

    return clamp(risk, MIN_RISK_PCT, MAX_RISK_PCT)


def dynamic_leverage(
    score: float,
    atr_pct: float,
    liquidity: float,
) -> int:

    quality = clamp(
        (score - OMEGA_ENTRY_SCORE)
        / max(1.0, 100.0 - OMEGA_ENTRY_SCORE),
        0,
        1,
    )

    lev = LEV_MIN + (LEV_MAX - LEV_MIN) * quality

    # Volatility and liquidity reduce leverage mechanically.
    if atr_pct > 3.0:
        lev *= 0.60
    elif atr_pct > 2.0:
        lev *= 0.75

    if liquidity < 40:
        lev *= 0.65
    elif liquidity < 60:
        lev *= 0.80

    return int(clamp(lev, LEV_MIN, LEV_MAX))


# ============================================================ DECISION

def build_signal(
    symbol: str,
    equity: float,
) -> Optional[Dict[str, Any]]:

    try:
        regime, atr_pct = alpha_core.detect_regime(symbol)
    except Exception as e:
        log.debug("regime %s: %s", symbol, e)
        return None

    if regime == "DEATH":
        return None

    try:
        base_ind = alpha_core.full_indicator_set(symbol, "15m")
    except Exception:
        return None

    if not base_ind:
        return None

    try:
        rev_score, rev_label = alpha_core.extreme_reversion_signal(base_ind)
        rev_score = finite(rev_score)
    except Exception:
        return None

    if abs(rev_score) < REVERSION_THRESHOLD:
        return None

    side = "LONG" if rev_score > 0 else "SHORT"

    quality = extreme_quality(base_ind, rev_score)

    score = quality["score"]

    if score < OMEGA_ENTRY_SCORE:
        return None

    mtf = collect_mtf(symbol)
    mtf_score, mtf_label = mtf_alignment(mtf, side)

    book = get_book(symbol)
    liq_score = liquidity_score(book)

    if book["spread_bps"] > MAX_SPREAD_BPS:
        return None

    # MTF confirms, never overrides the core reversal.
    final_score = (
        score * 0.72
        + mtf_score * 0.14
        + liq_score * 0.14
    )

    final_score = clamp(final_score, 0, 100)

    atr = max(
        finite(atr_pct),
        0.01,
    )

    tp_pct = max(
        MIN_TP_PCT,
        atr * (
            1.05 if final_score >= OMEGA_STRONG_SCORE else 0.90
        ),
    )

    sl_pct = max(
        MIN_SL_PCT,
        atr * 1.20,
    )

    ev = expected_edge(
        final_score,
        tp_pct,
        sl_pct,
    )

    # Maliyet sonrası negatif edge -> işlem yok.
    if ev["net_ev_pct"] <= 0:
        return None

    risk_pct = dynamic_risk(
        final_score,
        regime,
        atr,
    )

    lev = dynamic_leverage(
        final_score,
        atr,
        liq_score,
    )

    notional = min(
        MAX_NOTIONAL,
        equity * risk_pct * lev,
    )

    if notional <= 0:
        return None

    try:
        corr_block = alpha_core.correlation_blocked(
            symbol,
            side,
            [
                (s, m["side"])
                for s, m in _open_meta.items()
            ],
        )
    except Exception:
        corr_block = False

    if corr_block:
        return None

    signal = {
        "symbol": symbol,
        "side": side,
        "regime": regime,
        "rev_score": round(rev_score, 2),
        "score": round(final_score, 2),
        "core_score": quality["core"],
        "oscillator_score": quality["oscillator"],
        "band_score": quality["band"],
        "rsi_extreme": quality["rsi_extreme"],
        "ema_confirmation": quality["ema_confirmation"],
        "mtf_score": round(mtf_score, 2),
        "mtf_label": mtf_label,
        "liquidity": round(liq_score, 2),
        "spread_bps": round(book["spread_bps"], 3),
        "atr_pct": round(atr, 5),
        "tp_pct": round(tp_pct, 5),
        "sl_pct": round(sl_pct, 5),
        "risk_pct": round(risk_pct, 6),
        "leverage": lev,
        "notional": round(notional, 6),
        "rev_label": rev_label,
        "ev": ev,
        "ts": time.time(),
    }

    return signal


# ============================================================ AUDIT

def record_decision(
    signal: Dict[str, Any],
    opened: bool,
    reason: str,
) -> None:

    rec = {
        "ts": int(time.time()),
        "symbol": signal["symbol"],
        "side": signal["side"],
        "score": signal["score"],
        "opened": opened,
        "reason": reason,
        "regime": signal["regime"],
        "mtf": signal["mtf_score"],
        "liquidity": signal["liquidity"],
        "spread_bps": signal["spread_bps"],
        "tp_pct": signal["tp_pct"],
        "sl_pct": signal["sl_pct"],
        "risk_pct": signal["risk_pct"],
        "leverage": signal["leverage"],
        "ev": signal["ev"],
    }

    with _lock:
        _decision_log.insert(0, rec)
        del _decision_log[150:]

        _signal_book[signal["symbol"]] = signal
        if len(_signal_book) > 100:
            oldest = min(
                _signal_book,
                key=lambda k: _signal_book[k]["ts"],
            )
            _signal_book.pop(oldest, None)

    audit.append({
        "event": "DECISION",
        **rec,
    })


# ============================================================ OPEN

def open_signal(
    signal: Dict[str, Any],
) -> None:

    symbol = signal["symbol"]
    side = signal["side"]

    with _lock:
        if symbol in _open_meta:
            return

        if len(_open_meta) >= MAX_POSITIONS:
            return

    equity = get_wallet_equity()

    if portfolio_notional_blocked(
        signal["notional"],
        equity,
    ):
        record_decision(
            signal,
            False,
            "PORTFOLIO_LIMIT",
        )
        return

    if order_breaker.state() == "OPEN" and not order_breaker.allow():
        record_decision(
            signal,
            False,
            "CIRCUIT_BREAKER",
        )
        return

    if not is_live():
        record_decision(
            signal,
            False,
            "LIVE_ARMED=0",
        )
        return

    try:
        res = kernel.open_market(
            symbol,
            side,
            signal["risk_pct"],
            signal["leverage"],
            signal["tp_pct"],
            signal["sl_pct"],
            max_notional=MAX_NOTIONAL,
        )

        order_breaker.record_success()

    except Exception as e:
        order_breaker.record_failure()

        log.error(
            "OPEN FAIL %s %s: %s",
            side,
            symbol,
            e,
        )

        record_decision(
            signal,
            False,
            f"ORDER_FAIL:{e}",
        )
        return

    entry = finite(res.get("entry"))
    qty = finite(res.get("qty"))

    if entry <= 0 or qty <= 0:
        record_decision(
            signal,
            False,
            "INVALID_FILL",
        )
        return

    open_fee = entry * qty * FEE_RATE

    meta = {
        "side": side,
        "entry": entry,
        "qty": qty,
        "original_qty": qty,
        "tp": finite(res.get("tp")),
        "sl": finite(res.get("sl")),
        "lev": signal["leverage"],
        "open_fee": open_fee,
        "ts": time.time(),
        "regime": signal["regime"],
        "confidence": signal["score"],
        "score": signal["score"],
        "rev_score": signal["rev_score"],
        "trail_stage": 0,
        "realized_partial_net": 0.0,
        "ev": signal["ev"],
    }

    with _lock:
        _open_meta[symbol] = meta

    trail_engine.register(
        symbol,
        side,
        entry,
        meta["tp"],
        meta["sl"],
    )

    partial_engine.register(
        symbol,
        side,
        entry,
        meta["tp"],
        meta["sl"],
        qty=qty,
        pos_side=res.get("pos_side"),
    )

    audit.append({
        "event": "OPEN",
        "symbol": symbol,
        "side": side,
        "entry": entry,
        "qty": qty,
        "lev": signal["leverage"],
        "score": signal["score"],
        "rev_score": signal["rev_score"],
        "regime": signal["regime"],
        "ev": signal["ev"],
    })

    record_decision(
        signal,
        True,
        "LIVE_OPEN",
    )

    log.info(
        "OPEN %s %s | SCORE=%.1f CORE=%.1f MTF=%.1f LIQ=%.1f "
        "LEV=%dx TP=%.3f%% SL=%.3f%% EV=%.4f%%",
        side,
        symbol,
        signal["score"],
        signal["core_score"],
        signal["mtf_score"],
        signal["liquidity"],
        signal["leverage"],
        signal["tp_pct"],
        signal["sl_pct"],
        signal["ev"]["net_ev_pct"],
    )


# ============================================================ MANAGEMENT

def manage_positions() -> None:

    with _lock:
        symbols = list(_open_meta.keys())

    now = time.time()

    for symbol in symbols:

        with _lock:
            meta = _open_meta.get(symbol)

        if not meta:
            continue

        try:
            book = get_book(symbol)
            mid = book["mid"]

            if mid <= 0:
                continue

            # Dynamic trailing
            new_sl = trail_engine.update(
                symbol,
                mid,
            )

            if new_sl is not None:
                with _lock:
                    if symbol in _open_meta:
                        _open_meta[symbol]["sl"] = finite(new_sl)

            # Partial profit
            partial_res = partial_engine.update(
                symbol,
                mid,
            )

            if partial_res is not None:
                with _lock:
                    if symbol in _open_meta:
                        _open_meta[symbol]["qty"] = finite(
                            partial_res.get("remaining")
                        )
                        _open_meta[symbol]["realized_partial_net"] += finite(
                            partial_res.get("net")
                        )

                audit.append({
                    "event": "PARTIAL_CLOSE",
                    "symbol": symbol,
                    **partial_res,
                })

            # Tactical timeout.
            if now - finite(meta.get("ts")) > MAX_HOLD_SEC:
                try:
                    log.info(
                        "TACTICAL TIMEOUT %s %s",
                        meta["side"],
                        symbol,
                    )
                except Exception:
                    pass

        except Exception as e:
            log.debug(
                "MANAGE %s: %s",
                symbol,
                e,
            )


def check_closed_positions() -> None:

    with _lock:
        symbols = list(_open_meta.keys())

    for symbol in symbols:

        with _lock:
            meta = _open_meta.get(symbol)

        if not meta:
            continue

        try:
            real_amt = abs(
                finite(
                    kernel.position_amt(
                        symbol,
                        meta["side"],
                    )
                )
            )
        except Exception:
            continue

        if real_amt > 1e-12:
            continue

        try:
            exit_px = get_book(symbol)["mid"]
        except Exception:
            exit_px = meta["entry"]

        exit_px = exit_px or meta["entry"]

        close_fee = (
            exit_px
            * max(0.0, finite(meta.get("qty")))
            * FEE_RATE
        )

        raw = (
            (exit_px - meta["entry"]) * meta["qty"]
            if meta["side"] == "LONG"
            else
            (meta["entry"] - exit_px) * meta["qty"]
        )

        net = (
            raw
            - close_fee
            - meta.get("open_fee", 0.0)
            + meta.get("realized_partial_net", 0.0)
        )

        rec = {
            "symbol": symbol,
            "side": meta["side"],
            "entry": meta["entry"],
            "exit": exit_px,
            "net_pnl": round(net, 8),
            "hold_sec": round(
                time.time() - meta["ts"],
                2,
            ),
            "regime": meta["regime"],
            "score": meta["score"],
            "lev": meta["lev"],
            "closed_ts": int(time.time()),
        }

        with _lock:
            _journal.insert(0, rec)
            del _journal[300:]
            _open_meta.pop(symbol, None)

        try:
            trail_engine.forget(symbol)
        except Exception:
            pass

        try:
            partial_engine.forget(symbol)
        except Exception:
            pass

        try:
            alpha_core.on_trade_closed(
                symbol,
                meta["side"],
                net,
                meta["confidence"],
                meta["regime"],
            )
        except Exception:
            pass

        audit.append({
            "event": "CLOSE",
            **rec,
        })

        log.info(
            "CLOSE %s %s NET=%+.6f HOLD=%.1fs SCORE=%.1f",
            meta["side"],
            symbol,
            net,
            rec["hold_sec"],
            meta["score"],
        )


# ============================================================ SCAN

def scan_symbol(
    symbol: str,
    equity: float,
) -> None:

    with _lock:
        if symbol in _open_meta:
            return

        if len(_open_meta) >= MAX_POSITIONS:
            return

    signal = build_signal(
        symbol,
        equity,
    )

    if not signal:
        return

    record_decision(
        signal,
        False,
        "QUALIFIED",
    )

    log.info(
        "CANDIDATE %s %s | SCORE %.1f | CORE %.1f | MTF %.1f | "
        "LIQ %.1f | ATR %.3f%% | EV %.4f%% | %s",
        signal["side"],
        symbol,
        signal["score"],
        signal["core_score"],
        signal["mtf_score"],
        signal["liquidity"],
        signal["atr_pct"],
        signal["ev"]["net_ev_pct"],
        signal["rev_label"],
    )

    open_signal(signal)


# ============================================================ LOOP

def main_loop() -> None:

    log.info(
        "OMEGA ONLINE | symbols=%d max_pos=%d "
        "threshold=%.1f entry=%.1f mode=%s armed=%s TF=%s",
        len(WIDE_SYMBOLS),
        MAX_POSITIONS,
        REVERSION_THRESHOLD,
        OMEGA_ENTRY_SCORE,
        EXECUTION_MODE,
        rget("live_armed"),
        ",".join(TIMEFRAMES),
    )

    while True:

        cycle_start = time.time()

        try:
            rset(
                "cycle",
                int(rget("cycle") or 0) + 1,
            )

            check_closed_positions()

            if is_live():
                manage_positions()

            equity = get_wallet_equity()

            if equity <= 0:
                log.error("EQUITY=0 -> scan atlandı.")
                time.sleep(5)
                continue

            for symbol in WIDE_SYMBOLS:

                try:
                    scan_symbol(
                        symbol,
                        equity,
                    )
                except Exception as e:
                    log.error(
                        "SCAN FAIL %s: %s",
                        symbol,
                        e,
                    )

                time.sleep(
                    max(0.05, SYMBOL_DELAY_SEC)
                )

            elapsed = time.time() - cycle_start

            sleep_for = max(
                0.25,
                SCAN_INTERVAL_SEC - elapsed,
            )

            time.sleep(sleep_for)

        except KeyboardInterrupt:
            log.info("OMEGA STOP")
            break

        except Exception as e:
            log.error(
                "MAIN LOOP: %s",
                e,
            )
            time.sleep(5)


# ============================================================ HTTP PANEL

class Handler(BaseHTTPRequestHandler):

    def _send(
        self,
        status: int,
        payload: Dict[str, Any],
    ) -> None:

        body = json.dumps(
            payload,
            ensure_ascii=False,
            default=str,
        ).encode("utf-8")

        self.send_response(status)
        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8",
        )
        self.send_header(
            "Content-Length",
            str(len(body)),
        )
        self.end_headers()
        self.wfile.write(body)

    def _send_html(
        self,
        body: str,
    ) -> None:

        raw = body.encode("utf-8")

        self.send_response(200)
        self.send_header(
            "Content-Type",
            "text/html; charset=utf-8",
        )
        self.send_header(
            "Content-Length",
            str(len(raw)),
        )
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):

        path = self.path.split("?")[0]

        if path in ("/", "/panel"):

            with _lock:
                positions = [
                    {
                        "symbol": s,
                        **m,
                    }
                    for s, m in _open_meta.items()
                ]

                journal = list(_journal[:30])
                decisions = list(_decision_log[:40])

            total_net = sum(
                finite(x.get("net_pnl"))
                for x in journal
            )

            pos_rows = ""

            for p in positions:
                pos_rows += (
                    "<tr>"
                    f"<td>{html.escape(p['symbol'])}</td>"
                    f"<td>{html.escape(p['side'])}</td>"
                    f"<td>{p['entry']:.8f}</td>"
                    f"<td>{p['lev']}x</td>"
                    f"<td>{p['score']:.1f}</td>"
                    f"<td>{html.escape(p['regime'])}</td>"
                    "</tr>"
                )

            if not pos_rows:
                pos_rows = (
                    "<tr><td colspan='6'>Açık pozisyon yok</td></tr>"
                )

            j_rows = ""

            for r in journal:
                j_rows += (
                    "<tr>"
                    f"<td>{html.escape(r['symbol'])}</td>"
                    f"<td>{html.escape(r['side'])}</td>"
                    f"<td>{r['net_pnl']:+.6f}</td>"
                    f"<td>{r['hold_sec']:.1f}s</td>"
                    f"<td>{r.get('score', 0):.1f}</td>"
                    "</tr>"
                )

            if not j_rows:
                j_rows = (
                    "<tr><td colspan='5'>Henüz kapanan yok</td></tr>"
                )

            d_rows = ""

            for d in decisions:
                d_rows += (
                    "<tr>"
                    f"<td>{time.strftime('%H:%M:%S', time.localtime(d['ts']))}</td>"
                    f"<td>{html.escape(d['symbol'])}</td>"
                    f"<td>{html.escape(d['side'])}</td>"
                    f"<td>{d['score']:.1f}</td>"
                    f"<td>{html.escape(d['reason'])}</td>"
                    "</tr>"
                )

            if not d_rows:
                d_rows = (
                    "<tr><td colspan='5'>Henüz karar yok</td></tr>"
                )

            armed = "ON" if rget("live_armed") else "OFF"

            page = f"""
<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="5">
<title>Honeycomb Extreme Scanner OMEGA</title>
<style>
body{{background:#080d13;color:#d9e4ec;font-family:system-ui;margin:0;padding:18px}}
h1{{font-size:20px}}
h2{{font-size:14px;margin-top:25px}}
table{{width:100%;border-collapse:collapse;font-size:12px}}
th,td{{padding:7px;border-bottom:1px solid #23313d;text-align:left}}
th{{color:#8fa5b5}}
.badge{{padding:4px 8px;border-radius:6px;background:#17222d}}
</style>
</head>
<body>
<h1>HONEYCOMB EXTREME SCANNER OMEGA</h1>
<p>
MODE=<b>{EXECUTION_MODE}</b>
ARMED=<b>{armed}</b>
SYMBOLS=<b>{len(WIDE_SYMBOLS)}</b>
OPEN=<b>{len(positions)}/{MAX_POSITIONS}</b>
CYCLE=<b>{rget('cycle')}</b>
</p>

<h2>Net P/L</h2>
<div class="badge">{total_net:+.8f}</div>

<h2>Açık Pozisyonlar</h2>
<table>
<tr>
<th>Sembol</th><th>Yön</th><th>Entry</th>
<th>Lev</th><th>Score</th><th>Rejim</th>
</tr>
{pos_rows}
</table>

<h2>Kapanan İşlemler</h2>
<table>
<tr>
<th>Sembol</th><th>Yön</th><th>Net</th>
<th>Hold</th><th>Score</th>
</tr>
{j_rows}
</table>

<h2>Karar Kanıtları</h2>
<table>
<tr>
<th>Saat</th><th>Sembol</th><th>Yön</th>
<th>Score</th><th>Karar</th>
</tr>
{d_rows}
</table>

</body>
</html>
"""

            self._send_html(page)
            return

        if path == "/status":

            with _lock:
                payload = {
                    "engine": "EXTREME_SCANNER_OMEGA",
                    "mode": EXECUTION_MODE,
                    "live_armed": bool(rget("live_armed")),
                    "venue": VENUE,
                    "symbols": len(WIDE_SYMBOLS),
                    "open": len(_open_meta),
                    "max_positions": MAX_POSITIONS,
                    "cycle": rget("cycle"),
                    "entry_score": OMEGA_ENTRY_SCORE,
                    "threshold": REVERSION_THRESHOLD,
                    "timeframes": TIMEFRAMES,
                }

            self._send(
                200,
                payload,
            )
            return

        if path == "/signals":

            with _lock:
                rows = sorted(
                    _signal_book.values(),
                    key=lambda x: x["score"],
                    reverse=True,
                )[:50]

            self._send(
                200,
                {
                    "count": len(rows),
                    "signals": rows,
                },
            )
            return

        if path == "/positions":

            with _lock:
                rows = [
                    {
                        "symbol": s,
                        **m,
                    }
                    for s, m in _open_meta.items()
                ]

            self._send(
                200,
                {
                    "count": len(rows),
                    "positions": rows,
                },
            )
            return

        if path == "/journal":

            with _lock:
                rows = list(_journal[:100])

            self._send(
                200,
                {
                    "count": len(rows),
                    "journal": rows,
                },
            )
            return

        self._send(
            404,
            {"error": "NOT_FOUND"},
        )

    def do_POST(self):

        path = self.path.split("?")[0]

        if path != "/control":
            self._send(
                404,
                {"error": "NOT_FOUND"},
            )
            return

        length = int(
            self.headers.get(
                "Content-Length",
                0,
            )
        )

        raw = (
            self.rfile.read(length)
            .decode("utf-8")
            if length
            else "{}"
        )

        try:
            payload = json.loads(raw)
        except Exception:
            payload = {}

        if "live_armed" in payload:
            rset(
                "live_armed",
                bool(payload["live_armed"]),
            )

        self._send(
            200,
            {
                "ok": True,
                "runtime": dict(RUNTIME),
            },
        )

    def log_message(self, *_a):
        return


# ============================================================ BRIDGE

def start_bridge() -> None:

    port = BRIDGE_PORT

    for _ in range(10):

        try:
            server = ThreadingHTTPServer(
                (
                    BRIDGE_HOST,
                    port,
                ),
                Handler,
            )
            break

        except OSError:
            port += 1

    else:
        log.error("Bridge başlatılamadı.")
        return

    log.info(
        "OMEGA PANEL http://%s:%d",
        BRIDGE_HOST,
        port,
    )

    server.serve_forever()


# ============================================================ MAIN

def main() -> None:

    t = threading.Thread(
        target=start_bridge,
        daemon=True,
        name="omega-bridge",
    )

    t.start()

    main_loop()


if __name__ == "__main__":
    main()
=======
"""Compatibility alias — historical filename extreme_scanner_omega.py."""
from extreme_scanner_engine import *  # noqa: F401,F403
from extreme_scanner_engine import main_loop

if __name__ == "__main__":
    main_loop()
>>>>>>> refs/remotes/origin/main
