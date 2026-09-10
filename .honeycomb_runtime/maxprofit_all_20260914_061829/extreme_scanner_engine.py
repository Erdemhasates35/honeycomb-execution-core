#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HONEYCOMB EXTREME SCANNER ENGINE — tactical reversal (LIVE).

Uses alpha_core.get_technical_decision / evaluate_entry_gate.
klines lives in alpha_core — this file never assumes a global klines.
"""
from __future__ import annotations


# MAXIMUM PROFIT LAYER
def dynamic_tp_sl_maxprofit(atr_pct, score, regime="RANGE", confidence=70.0):
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
    mfe = max(0.0, float(mfe_pct or 0.0))
    atr_pct = max(0.12, float(atr_pct or 0.7))
    if mfe < atr_pct * 0.60:
        return 0.0
    base = atr_pct * (0.15 if stage <= 0 else 0.29 if stage == 1 else 0.46)
    lock = base + mfe * 0.24
    return round(min(mfe * 0.78, lock), 4)

def cost_aware_net_edge(raw_edge_or_score, atr_pct, fee=0.0004, slip_bps=2.0):
    gross = abs(float(raw_edge_or_score or 0.0))
    if gross > 5:
        gross = (gross / 100.0) * (float(atr_pct or 0.7) / 100.0) * 2.5
    cost = float(fee) * 2.0 + (float(slip_bps) / 10000.0)
    return gross - cost

def volatility_size_boost(atr_pct, confidence=70.0, base_risk=0.08):
    atr_pct = max(0.15, float(atr_pct or 0.8))
    scale = max(0.50, min(1.75, 0.88 / atr_pct))
    if confidence and float(confidence) > 78:
        scale *= 1.10
    return round(min(0.12, float(base_risk) * scale), 4)

def regime_tp_boost(regime, score):
    if str(regime).upper() in ("TREND", "TREND_UP", "TREND_DOWN"):
        return 1.0 + 0.38 * max(0.0, min(1.0, (float(score) - 50) / 40.0))
    return 1.0


import logging
import os
import sys
import time
from typing import Any, Dict, List, Tuple

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from live.kernel import (
    LiveKernel,
    DynamicTrailingStopEngine,
    PartialProfitEngine,
    CircuitBreaker,
    CryptographicAuditLedger,
    load_env,
)
import alpha_core

try:
    for _k, _v in load_env().items():
        os.environ.setdefault(_k, _v)
except Exception as _e:
    print("UYARI .env: %s" % _e, flush=True)

ACCOUNT_LABEL = os.getenv("ACCOUNT_LABEL", "SCANNER-OMEGA")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [OMEGA:%s] %%(message)s" % ACCOUNT_LABEL,
    datefmt="%H:%M:%S",
)
log = logging.getLogger("extreme_scanner_engine")

VENUE = os.getenv("VENUE", "usdt").lower()
DEFAULT_WIDE = (
    "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,ADAUSDT,DOGEUSDT,"
    "AVAXUSDT,LINKUSDT,LTCUSDT,DOTUSDT,TRXUSDT,ATOMUSDT,NEARUSDT"
)
WIDE_SYMBOLS = [s.strip().upper() for s in os.getenv("WIDE_SYMBOLS", DEFAULT_WIDE).split(",") if s.strip()]
MAX_POSITIONS = int(os.getenv("SCANNER_MAX_POSITIONS", "8"))
SCAN_INTERVAL_SEC = float(os.getenv("SCANNER_INTERVAL_SEC", "12"))
SYMBOL_DELAY_SEC = float(os.getenv("SCANNER_SYMBOL_DELAY_SEC", "0.35"))
AUDIT_FILE = os.path.join(ROOT, os.getenv("SCANNER_AUDIT_FILE", "scanner_omega_audit.jsonl"))

kernel = LiveKernel(venue=VENUE, log_fn=lambda m: log.info(m))
kernel.load_exchange_info(WIDE_SYMBOLS)
trail_engine = DynamicTrailingStopEngine(kernel, log_fn=lambda m: log.info(m))
partial_engine = PartialProfitEngine(kernel, log_fn=lambda m: log.info(m))
order_breaker = CircuitBreaker(fail_threshold=4, cooldown_sec=180)
audit = CryptographicAuditLedger(AUDIT_FILE)
_open_meta: Dict[str, Dict[str, Any]] = {}


def open_positions_list() -> List[Tuple[str, str]]:
    return [(s, m.get("side", "")) for s, m in _open_meta.items()]


def scan_symbol(symbol: str) -> None:
    if not order_breaker.allow():
        log.warning("circuit open — skip %s", symbol)
        return
    if len(_open_meta) >= MAX_POSITIONS:
        return
    if symbol in _open_meta:
        return
    try:
        equity = max(0.0, float(kernel.balance_usdt() or 0.0))
    except Exception as e:
        log.warning("equity: %s", e)
        equity = 0.0
    tech = alpha_core.get_technical_decision(symbol, equity=equity, open_positions=open_positions_list())
    if not tech.get("allow"):
        log.info("FILTER %s %s conf=%s", symbol, tech.get("reason"), tech.get("confidence"))
        return
    side = tech["side"]
    risk_pct = float(tech.get("risk_pct") or os.getenv("SCANNER_RISK", "0.015"))
    lev = int(tech.get("leverage") or 10)
    tp_pct = max(0.20, float(os.getenv("SCANNER_MIN_TP_PCT", "0.20")))
    sl_pct = max(0.30, float(os.getenv("SCANNER_MIN_SL_PCT", "0.30")))
    max_notional = float(os.getenv("MAX_POSITION_SIZE_USDT", "500"))
    if os.getenv("LIVE_ARMED", "0") != "1":
        log.info("PAPER GATE %s %s score=%s", symbol, side, tech.get("score"))
        audit.append({"event": "paper", "symbol": symbol, "tech": {k: tech[k] for k in tech if k != "details"}})
        return
    try:
        res = kernel.open_market(symbol, side, risk_pct, lev, tp_pct, sl_pct, max_notional=max_notional)
        _open_meta[symbol] = {
            "side": side, "entry": res["entry"], "qty": res["qty"], "lev": lev,
            "tp": res["tp"], "sl": res["sl"], "confidence": tech.get("confidence"),
            "regime": tech.get("regime"),
        }
        trail_engine.register(symbol, side, res["entry"], res["tp"], res["sl"])
        partial_engine.register(symbol, side, res["entry"], res["tp"], res["sl"], res["qty"], res.get("pos_side"))
        order_breaker.record_success()
        audit.append({"event": "open", "symbol": symbol, "res": res, "tech": tech.get("reason")})
        log.info("OPEN %s %s", side, symbol)
    except Exception as e:
        order_breaker.record_failure()
        log.error("OPEN HATA %s: %s", symbol, e)


def check_closed_positions() -> None:
    for symbol, meta in list(_open_meta.items()):
        try:
            real_amt = kernel.position_amt(symbol, meta["side"])
        except Exception as e:
            log.warning("pos %s: %s", symbol, e)
            continue
        if real_amt > 0:
            try:
                bid, ask, mid = kernel.book(symbol)
                trail_engine.update(symbol, mid)
                partial_engine.update(symbol, mid)
            except Exception:
                pass
            continue
        net = 0.0
        alpha_core.on_trade_closed(symbol, meta["side"], net, meta.get("confidence") or 0, meta.get("regime") or "")
        trail_engine.forget(symbol)
        partial_engine.forget(symbol)
        _open_meta.pop(symbol, None)
        log.info("CLOSED %s", symbol)


def main_loop() -> None:
    log.info("exchangeInfo loaded filters=%s symbols=%s LIVE_ARMED=%s",
             len(getattr(kernel, "_filters", {})), len(WIDE_SYMBOLS), os.getenv("LIVE_ARMED", "0"))
    log.info("PANEL http://127.0.0.1:%s", os.getenv("HONEYCOMB_SCANNER_PORT", "8200"))
    while True:
        check_closed_positions()
        for sym in WIDE_SYMBOLS:
            try:
                scan_symbol(sym)
            except Exception as e:
                log.error("DONGU HATASI: %s", e)
            time.sleep(SYMBOL_DELAY_SEC)
        time.sleep(SCAN_INTERVAL_SEC)


if __name__ == "__main__":
    main_loop()
