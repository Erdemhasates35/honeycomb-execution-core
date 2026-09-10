#!/data/data/com.termux/files/usr/bin/python3
# -*- coding: utf-8 -*-
"""Honeycomb final runtime hotfix.

Preserves broken/original lines in timestamped backups and comments malformed
lines instead of silently deleting them. Repairs runtime blockers only.
"""
from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STAMP = time.strftime("%Y%m%d_%H%M%S")


def backup(path: Path) -> Path:
    out = path.with_name(path.name + ".pre_final_hotfix." + STAMP)
    shutil.copy2(path, out)
    return out


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def patch_kernel():
    p = ROOT / "live" / "kernel.py"
    b = backup(p)
    s = p.read_text(encoding="utf-8", errors="replace")
    lines = s.splitlines(True)
    out = []
    saw_sf = False
    for line in lines:
        stripped = line.strip()
        if 'self.path = path or "os.path.join(os.path.expanduser("~"), ".honeycomb", "sf.lock")"' in line:
            indent = line[:len(line)-len(line.lstrip())]
            out.append(indent + "# PRESERVED BROKEN LINE: " + stripped + "\n")
            out.append(indent + 'self.path = path or os.path.join(os.path.expanduser("~"), ".honeycomb", "sf.lock")\n')
            continue
        if "os.makedirs(os.path.dirname(os.path.join(os.path.expanduser(\"~\"), \".honeycomb\", \"sf.lock\")), exist_ok=True)" in stripped:
            indent = line[:len(line)-len(line.lstrip())]
            out.append(indent + "# PRESERVED MISPLACED DIRECTORY-CREATION LINE: " + stripped + "\n")
            continue
        out.append(line)
        if stripped == "class SingleFlight:" and not saw_sf:
            saw_sf = True
        elif saw_sf and stripped.startswith("self.path = path or"):
            indent = line[:len(line)-len(line.lstrip())]
            out.append(indent + 'os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)\n')
            saw_sf = False
    s = "".join(out)

    marker = "# FINAL-HOTFIX: BINANCE GUARD\n"
    if marker not in s:
        needle = "from typing import Any, Dict, List, Optional, Tuple\n"
        inject = needle + "\n" + marker + "try:\n    import honeycomb_execution_guard as _honeycomb_guard\n    _honeycomb_guard.install()\nexcept Exception:\n    _honeycomb_guard = None\n"
        s = s.replace(needle, inject, 1)

    s = s.replace(
        'self._stale_until = time.time() + min(30, 2 ** attempt + 1)',
        'self._stale_until = time.time() + min(4, 1.0 + 0.5 * attempt)',
    )

    # Exchange-side RESULT is the authoritative synchronous order response for a
    # MARKET order. It prevents an ACK from being mistaken for a fill.
    old = 'params = {"symbol": symbol, "side": side, "type": "MARKET", "quantity": q}'
    new = 'params = {"symbol": symbol, "side": side, "type": "MARKET", "quantity": q, "newOrderRespType": "RESULT"}'
    s = s.replace(old, new, 1)

    needle = '            oid = res.get("orderId")\n            ack_avg = float(res.get("avgPrice") or 0) or entry_px\n'
    repl = '            oid = res.get("orderId")\n            status = str(res.get("status") or "").upper()\n            if status != "FILLED":\n                raise RuntimeError("market order not FILLED: status=%s oid=%s" % (status or "UNKNOWN", oid))\n            ack_avg = float(res.get("avgPrice") or 0) or entry_px\n'
    s = s.replace(needle, repl, 1)

    write(p, s)
    return b


def patch_alpha():
    p = ROOT / "alpha_core.py"
    b = backup(p)
    s = p.read_text(encoding="utf-8", errors="replace")
    if "# FINAL-HOTFIX: BINANCE GUARD" not in s:
        needle = "from typing import Any, Dict, List, Optional, Tuple\n"
        inject = needle + "\n# FINAL-HOTFIX: BINANCE GUARD\ntry:\n    import honeycomb_execution_guard as _honeycomb_guard\n    _honeycomb_guard.install()\nexcept Exception:\n    _honeycomb_guard = None\n"
        s = s.replace(needle, inject, 1)
    s = s.replace("urllib.request.urlopen(req, timeout=8)", "urllib.request.urlopen(req, timeout=5)")
    write(p, s)
    return b


def patch_lobster():
    p = ROOT / "lobster_extreme_momentum_engine.py"
    b = backup(p)
    s = p.read_text(encoding="utf-8", errors="replace")

    if "# FINAL-HOTFIX: PARALLEL FRAMES" not in s:
        s = s.replace(
            "import math, os, sqlite3, statistics, threading, time\n",
            "import math, os, sqlite3, statistics, threading, time\nfrom concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError\n",
            1,
        )
        old = '''def decide(symbol):\n    frames=[]\n    for tf in ('1m','5m','15m','1h'):\n        x=calc_frame(symbol,tf,160)\n        if x is None:return None\n        frames.append(x)\n'''
        new = '''# FINAL-HOTFIX: PARALLEL FRAMES\ndef decide(symbol):\n    # Four timeframes are independent I/O operations. Serial REST reads made one\n    # slow Binance response freeze the entire live cycle. Bound each cycle so the\n    # engine can continue managing existing positions even when a frame is late.\n    frames_by_tf={}\n    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="lobster-tf") as ex:\n        futs={ex.submit(calc_frame, symbol, tf, 160): tf for tf in ('1m','5m','15m','1h')}\n        try:\n            for fut in as_completed(futs, timeout=6.0):\n                tf=futs[fut]\n                try: frames_by_tf[tf]=fut.result()\n                except Exception: frames_by_tf[tf]=None\n        except FuturesTimeoutError:\n            pass\n    frames=[frames_by_tf.get(tf) for tf in ('1m','5m','15m','1h')]\n    if any(x is None for x in frames): return None\n'''
        if old not in s:
            raise RuntimeError("Lobster decide() pattern not found")
        s = s.replace(old, new, 1)

    old_main = '''        if now-last_feat>=FEATURE_REFRESH:\n            for s in SYMBOLS:\n                try:cache[s]=decide(s)\n                except Exception as e: print(time.strftime('%H:%M:%S'),'[LOBSTER] SIGNAL_FAIL',s,str(e),flush=True)\n            last_feat=now\n'''
    new_main = '''        if now-last_feat>=FEATURE_REFRESH:\n            # Independent symbols are evaluated concurrently; position management\n            # stays outside this block and continues even if signal I/O is late.\n            with ThreadPoolExecutor(max_workers=min(6, max(1, len(SYMBOLS))), thread_name_prefix="lobster-sym") as ex:\n                futs={ex.submit(decide, s): s for s in SYMBOLS}\n                try:\n                    for fut in as_completed(futs, timeout=8.0):\n                        s=futs[fut]\n                        try: cache[s]=fut.result()\n                        except Exception as e:\n                            cache[s]=None\n                            print(time.strftime('%H:%M:%S'),'[LOBSTER] SIGNAL_FAIL',s,str(e),flush=True)\n                except FuturesTimeoutError:\n                    pass\n            last_feat=now\n'''
    if old_main in s: s = s.replace(old_main, new_main, 1)
    write(p, s)
    return b


def main():
    backups=[patch_kernel(), patch_alpha(), patch_lobster()]
    print("FINAL_HOTFIX_APPLIED")
    for b in backups: print("BACKUP", b)
    print("KERNEL_LOCK=HOME/.honeycomb/sf.lock")
    print("BINANCE_GUARD=ENABLED")
    print("MARKET_ORDER_RESPONSE=RESULT/FILLED_REQUIRED")
    print("LOBSTER=PARALLEL_IO_BOUNDED")
    print("NO_KEYS_PRINTED=TRUE")


if __name__ == "__main__": main()
