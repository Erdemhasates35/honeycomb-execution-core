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
    tech = alpha_core.get_technical_decision(symbol) or {}
    # Defensive contract: old/third-party alpha cores may omit optional keys.
    # Missing permission is always interpreted as DENY, never as approval.
    allow = bool(tech.get("allow", False))
    side = tech.get("side")
    print("PARLIAMENT %s allow=%s side=%s conf=%s regime=%s reason=%s" % (
        symbol, allow, side, tech.get("confidence", 0), tech.get("regime", "UNKNOWN"), tech.get("reason", "missing-decision-key")
    ), flush=True)


def main() -> None:
    print("SOVEREIGN PARLIAMENT ENGINE — alpha_core.get_technical_decision OK", flush=True)
    print("DEFENSE_ENABLED=%s" % alpha_core.DEFENSE_ENABLED, flush=True)
    scan_sleep = max(1.0, float(os.getenv("SCAN_SYMBOL_DELAY_SEC", "1.0")))
    cycle_sleep = max(10.0, float(os.getenv("SCAN_INTERVAL_SEC", "20")))
    while True:
        if not breaker.allow():
            time.sleep(2)
            continue
        cycle_failed = False
        for s in SYMBOLS:
            try:
                scan_symbol(s)
            except Exception as e:
                cycle_failed = True
                breaker.record_failure()
                print("PARLIAMENT HATA %s: %s" % (s, e), flush=True)
            time.sleep(scan_sleep)
        if cycle_failed:
            # A rate-limit/auth/network failure must cool down rather than poll harder.
            time.sleep(max(cycle_sleep, 30.0))
        else:
            breaker.record_success()
            time.sleep(cycle_sleep)


if __name__ == "__main__":
    main()
