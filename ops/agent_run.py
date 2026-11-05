#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bir motor = bir süreç. Anahtar .env'den okunur, ekrana yazılmaz."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# id, dosya, imza gerekir mi, ne işe yarar
AGENTS = (
    ("helix", "helix_sovereign_pro.py", True, "Canlı/testnet emir. Bakiye 0 ise girmez."),
    ("sovereign", "ai_sovereign_engine.py", True, "Ajan oylaması. 401/-2015 ise durur."),
    ("lobster", "lobster_extreme_momentum_engine.py", True, "Momentum emri. Ayrı süreç."),
    ("parliament", "sovereign_parliament_engine.py", True, "Parlamento. Ayrı süreç."),
    ("profit_max", "profit_max_engine.py", True, "Kâr motoru. Ayrı süreç."),
    ("quantum", "quantum_live_engine.py", True, "Quantum live. Ayrı süreç."),
    ("scanner", "extreme_scanner_engine.py", False, "Tarama. Emir bu dosyada yok."),
    ("quant", "autonomous_quant_engine.py", False, "Ölçüm. Emir bu kapıdan açılmaz."),
)


def load_env(path: Path) -> int:
    if not path.is_file():
        return 0
    n = 0
    raw = path.read_text(encoding="utf-8-sig")
    for line in raw.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if not k:
            continue
        os.environ[k] = v
        n += 1
    return n


def signed() -> bool:
    key = os.environ.get("BINANCE_API_KEY") or os.environ.get("BINANCE_TESTNET_API_KEY") or ""
    sec = (
        os.environ.get("BINANCE_API_SECRET")
        or os.environ.get("BINANCE_SECRET_KEY")
        or os.environ.get("BINANCE_SECRET")
        or os.environ.get("BINANCE_TESTNET_SECRET")
        or ""
    )
    return bool(key.strip() and sec.strip())


def cmd_list() -> int:
    print("GELIR: borsa gerçekleşen PnL. Bu liste rakam yazmaz.")
    mode = os.environ.get("HONEYCOMB_MODE") or os.environ.get("USE_TESTNET") or "env-yok"
    armed = os.environ.get("LIVE_ARMED", "0")
    print(f"ENV: {'var' if (ROOT / '.env').is_file() else 'YOK'}  IMZA: {'var' if signed() else 'yok'}  MOD: {mode}  ARMED: {armed}")
    for aid, fn, need, note in AGENTS:
        ok = (ROOT / fn).is_file()
        print(f"{aid:12} {'DOSYA' if ok else 'YOK':5} {'IMZA' if need else 'ACIK':4}  {note}")
    print("BASLAT: python3 ops/agent_run.py start <id>")
    print("Ayni anda tek id. Ikinci motor ayri Termux oturumunda.")
    return 0


def cmd_start(aid: str) -> int:
    row = next((a for a in AGENTS if a[0] == aid), None)
    if row is None:
        print("BILINMEYEN:", aid)
        cmd_list()
        return 2
    _, fn, need, note = row
    path = ROOT / fn
    if not path.is_file():
        print("DOSYA YOK:", fn)
        return 2
    if need and not signed():
        print("IMZA YOK. .env icinde BINANCE anahtari yok. Emir sureci acilmadi.")
        return 2
    print(f"BASLIYOR {aid} | {fn} | {note}")
    os.chdir(ROOT)
    os.execv(sys.executable, [sys.executable, str(path)])
    return 0


def main() -> int:
    os.chdir(ROOT)
    n = load_env(ROOT / ".env")
    if len(sys.argv) < 2 or sys.argv[1] == "list":
        print(f"OKUNAN_SATIR {n}")
        return cmd_list()
    if sys.argv[1] == "start":
        if len(sys.argv) < 3:
            print("start <id> gerekli")
            return cmd_list()
        return cmd_start(sys.argv[2])
    print("Kullanim: list | start <id>")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
