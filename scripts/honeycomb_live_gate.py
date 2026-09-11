#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Honeycomb single-pass LIVE gate.

No files are deleted. No trading order is created.
Backs up only files it may refresh, verifies the protection bridge, imports
LiveKernel, checks account/positions, and queries open algo orders.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKUP = ROOT / "backups" / f"live_gate_{time.strftime('%Y%m%d_%H%M%S')}"
BACKUP.mkdir(parents=True, exist_ok=True)

FILES = (
    "live/protection_bridge.py",
    "honeycomb_execution_guard.py",
    "binance_endpoint_failover.py",
    "sitecustomize.py",
)


def backup(path: Path) -> None:
    if path.is_file():
        target = BACKUP / path.name
        shutil.copy2(path, target)


def compile_all() -> None:
    targets = [
        "honeycomb_execution_guard.py",
        "binance_endpoint_failover.py",
        "sitecustomize.py",
        "live/kernel.py",
        "live/protection_bridge.py",
        "aggressive_live_engine.py",
        "aggressive_profit_optimizer.py",
        "lobster_extreme_momentum_engine.py",
    ]
    cmd = [sys.executable, "-m", "py_compile", *targets]
    subprocess.run(cmd, cwd=ROOT, check=True)


def main() -> int:
    os.chdir(ROOT)
    os.environ.setdefault("PYTHONPATH", str(ROOT))
    os.environ["EXECUTION_MODE"] = "LIVE"
    os.environ["HONEYCOMB_MODE"] = "LIVE"
    os.environ["LIVE_ARMED"] = "1"

    print(f"BACKUP={BACKUP}", flush=True)
    for rel in FILES:
        backup(ROOT / rel)

    compile_all()
    print("COMPILE_OK", flush=True)

    from live.kernel import LiveKernel, load_env
    import live.protection_bridge as bridge

    k = LiveKernel(venue="usdt", env=load_env())
    print("KERNEL_IMPORT_OK", flush=True)
    print("VENUE=", k.venue, flush=True)
    print("TIME_OFFSET=", getattr(k, "time_offset", getattr(k, "_off", None)), flush=True)
    print("PLACE_PROTECT=", callable(getattr(k, "place_protect", None)), flush=True)
    print("OPEN_ALGO_ORDERS=", callable(getattr(k, "open_algo_orders", None)), flush=True)
    print("BRIDGE_ALGO_ENDPOINT=", bridge._algo_endpoint(k), flush=True)

    print("========== ACCOUNT ==========")
    try:
        print("BALANCE=", k.balance())
    except Exception as exc:
        print("BALANCE_FAIL=", repr(exc))

    try:
        print("POSITION_MODE=", k.position_mode())
    except Exception as exc:
        print("POSITION_MODE_FAIL=", repr(exc))

    symbols = (
        "ADAUSDT", "XRPUSDT", "DOGEUSDT", "BTCUSDT", "ETHUSDT",
        "SOLUSDT", "BNBUSDT", "LINKUSDT", "LTCUSDT", "AVAXUSDT",
    )
    print("========== POSITIONS ==========")
    found = False
    for symbol in symbols:
        try:
            long_amt = k.position_amt(symbol, "LONG")
            short_amt = k.position_amt(symbol, "SHORT")
            if long_amt or short_amt:
                found = True
                print(symbol, "LONG=", long_amt, "SHORT=", short_amt)
        except Exception as exc:
            print(symbol, "POSITION_FAIL=", repr(exc))
    if not found:
        print("NO_NONZERO_POSITION_FOUND")

    print("========== OPEN ALGO ORDERS ==========")
    try:
        print(k.open_algo_orders())
    except Exception as exc:
        print("ALGO_QUERY_FAIL=", repr(exc))

    print("========== FINAL GATE ==========")
    print("NEW_ORDER_SENT=NO")
    print("BACKUP=", BACKUP)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
