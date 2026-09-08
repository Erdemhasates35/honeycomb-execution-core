#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Parliament engine shim — uses alpha_core.get_technical_decision.

Existing Helix Sovereign Pro remains untouched. This file only fills the
missing parliament surface that Termux logs required.
"""
from __future__ import annotations

import os
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import alpha_core
from live.kernel import LiveKernel, load_env, CircuitBreaker

try:
    for k, v in load_env().items():
        os.environ.setdefault(k, v)
except Exception:
    pass

kernel = LiveKernel(venue=os.getenv("VENUE", "usdt").lower(), log_fn=lambda m: print(m, flush=True))
breaker = CircuitBreaker()
SYMBOLS = [s.strip().upper() for s in os.getenv(
    "LIVE_SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT"
).split(",") if s.strip()]


def scan_symbol(symbol: str) -> None:
    tech = alpha_core.get_technical_decision(symbol)
    side = tech.get("side")
    print("PARLIAMENT %s allow=%s side=%s conf=%s regime=%s reason=%s" % (
        symbol, tech.get("allow"), side, tech.get("confidence"), tech.get("regime"), tech.get("reason")
    ), flush=True)


def main() -> None:
    print("SOVEREIGN PARLIAMENT ENGINE — alpha_core.get_technical_decision OK", flush=True)
    print("DEFENSE_ENABLED=%s" % alpha_core.DEFENSE_ENABLED, flush=True)
    while True:
        if not breaker.allow():
            time.sleep(2)
            continue
        for s in SYMBOLS:
            try:
                scan_symbol(s)
                breaker.record_success()
            except Exception as e:
                breaker.record_failure()
                print("PARLIAMENT HATA %s: %s" % (s, e), flush=True)
            time.sleep(0.4)
        time.sleep(float(os.getenv("SCAN_INTERVAL_SEC", "20")))


if __name__ == "__main__":
    main()
