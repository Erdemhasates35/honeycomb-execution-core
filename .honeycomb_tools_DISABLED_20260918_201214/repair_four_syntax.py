#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Honeycomb Deterministic Syntax Repair
=====================================

Amaç:
    Conflict-marker temizliği sonrasında kalan dört bilinen syntax
    bozulmasını deterministik ve korumacı biçimde düzeltmek.

GÜVENLİK İLKELERİ
-----------------
1. /tmp KULLANILMAZ.
2. Sadece repository root içindeki hedef dosyalar değiştirilir.
3. Her hedef dosyanın değişiklik öncesi SHA-256 özeti alınır.
4. Repo-local backup oluşturulur.
5. Exact block replacement kullanılır.
6. Beklenen blok tam olarak 1 kez bulunmazsa işlem ABORT eder.
7. Değişiklikten sonra py_compile çalışır.
8. Syntax başarısızsa backup otomatik geri yüklenir.
9. Live engine çalıştırılmaz.
10. .env, DB, logs, runtime ve backup kaynakları değiştirilmez.

Hedef:
    alpha_core.py
    live/kernel.py
    live/kernel_hardened_sign.py
    extreme_scanner_engine.py
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

TARGETS = [
    ROOT / "alpha_core.py",
    ROOT / "live" / "kernel.py",
    ROOT / "live" / "kernel_hardened_sign.py",
    ROOT / "extreme_scanner_engine.py",
]

BACKUP_ROOT = ROOT / ".honeycomb_tools" / "syntax_repair_backups"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def fail(message: str) -> None:
    print()
    print("[ABORT]")
    print(message)
    sys.exit(1)


def exact_replace(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)

    if count != 1:
        fail(
            f"{path.relative_to(ROOT)} :: {label}\n"
            f"Beklenen exact block = 1\n"
            f"Bulunan = {count}\n"
            f"Hiçbir değişiklik güvenli biçimde yapılamaz."
        )

    path.write_text(text.replace(old, new), encoding="utf-8")
    print(f"[PATCH] {path.relative_to(ROOT)} :: {label}")


def compile_target(path: Path) -> bool:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "py_compile",
            str(path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )

    if result.returncode == 0:
        print(f"[PASS] {path.relative_to(ROOT)}")
        return True

    print(f"[FAIL] {path.relative_to(ROOT)}")
    if result.stderr:
        print(result.stderr.rstrip())
    return False


def main() -> int:
    print("============================================================")
    print(" HONEYCOMB DETERMINISTIC SYNTAX REPAIR")
    print("============================================================")
    print(f"ROOT: {ROOT}")
    print("TEMP DIRECTORY: NONE")
    print()

    if not ROOT.is_dir():
        fail(f"Repository root bulunamadı: {ROOT}")

    for path in TARGETS:
        if not path.is_file():
            fail(f"Hedef dosya bulunamadı: {path}")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = BACKUP_ROOT / timestamp
    backup_dir.mkdir(parents=True, exist_ok=False)

    manifest = []

    print("[BACKUP] Repo-local backup oluşturuluyor...")

    for path in TARGETS:
        digest = sha256(path)

        relative = path.relative_to(ROOT)
        backup_path = backup_dir / relative
        backup_path.parent.mkdir(parents=True, exist_ok=True)

        shutil.copy2(path, backup_path)

        manifest.append(
            f"{relative}\t{digest}\n"
        )

        print(
            f"[BACKUP] {relative} "
            f"SHA256={digest}"
        )

    (backup_dir / "MANIFEST.sha256").write_text(
        "".join(manifest),
        encoding="utf-8",
    )

    print()
    print(f"[BACKUP COMPLETE] {backup_dir.relative_to(ROOT)}")
    print()

    # ========================================================
    # 1. alpha_core.py
    # ========================================================

    path = ROOT / "alpha_core.py"

    old = '''            raw = json.loads(r.read().decode())
# alpha_core.py — Honeycomb technical decision core.

Self-contained (own klines + indicators) so parliament/scanner never crash
with "klines is not defined" or circular live.__init__ imports.

Academic stack (max-profit / min-cost):
  1. Kelly Criterion (Thorp 1969)
  2. Volatility targeting (Moreira & Muir 2017, JFE)
  3. Time-series momentum (Moskowitz, Ooi, Pedersen 2012)
  4. Cost-aware EV (transaction-cost alpha literature)
  5. Wilder ATR adaptive trailing (1978)
  6. Triple-barrier style TP/SL (López de Prado)
  7. Liquidity/spread filter (Amihud 2002 analogue)
  8. Regime kill-switch (low-vol death / high-vol explosion)
  9. Correlation / concentration shield
  10. Expectancy-based risk multiplier (anti-martingale)
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import sys
import time
import urllib.request
from typing import Any, Dict, List, Optional, Tuple
'''

    new = '''            raw = json.loads(r.read().decode())
'''

    exact_replace(
        path,
        old,
        new,
        "orphan module header inside klines()",
    )

    # ========================================================
    # 2. live/kernel.py
    # ========================================================

    path = ROOT / "live" / "kernel.py"

    old = '''    GENESIS_HASH = "0" * 64
            self.fails = 0
            self.state = "CLOSED"

    def record_failure(self):
'''

    new = '''    GENESIS_HASH = "0" * 64

    def record_failure(self):
'''

    exact_replace(
        path,
        old,
        new,
        "orphan fails/state lines",
    )

    # ========================================================
    # 3. live/kernel_hardened_sign.py
    # ========================================================

    path = ROOT / "live" / "kernel_hardened_sign.py"

    old = '''    headers = {"X-MBX-APIKEY": self.key, "Content-Type": "application/x-www-form-urlencoded"}
        body = urllib.parse.urlencode(
            {str(k): str(v) for k, v in params.items() if v is not None}, doseq=True
        )

    url = self.v["rest"] + path + (("?" + body) if method.upper() == "GET" and body else "")
    data = body.encode("utf-8") if method.upper() != "GET" else None
    headers = {
        "X-MBX-APIKEY": self.key,
        "Content-Type": "application/x-www-form-urlencoded",
    }

    last_err = None
'''

    new = '''    headers = {"X-MBX-APIKEY": self.key, "Content-Type": "application/x-www-form-urlencoded"}

    last_err = None
'''

    exact_replace(
        path,
        old,
        new,
        "duplicate HTTP request preparation block",
    )

    # ========================================================
    # 4. extreme_scanner_engine.py
    # ========================================================

    path = ROOT / "extreme_scanner_engine.py"

    old = '''BRIDGE_PORT = int(os.getenv("HONEYCOMB_BRIDGE_PORT", "8200"))
    print("UYARI .env: %s" % _e, flush=True)

ACCOUNT_LABEL = os.getenv("ACCOUNT_LABEL", "SCANNER-OMEGA")
'''

    new = '''BRIDGE_PORT = int(os.getenv("HONEYCOMB_BRIDGE_PORT", "8200"))

ACCOUNT_LABEL = os.getenv("ACCOUNT_LABEL", "SCANNER-OMEGA")
'''

    exact_replace(
        path,
        old,
        new,
        "orphan .env warning statement",
    )

    # ========================================================
    # POST-PATCH INTEGRITY
    # ========================================================

    print()
    print("============================================================")
    print(" POST-PATCH SYNTAX VERIFICATION")
    print("============================================================")

    failed = []

    for path in TARGETS:
        if not compile_target(path):
            failed.append(path)

    if failed:
        print()
        print("[ROLLBACK] Syntax verification başarısız.")
        print("[ROLLBACK] Repo-local backup geri yükleniyor...")

        for path in TARGETS:
            relative = path.relative_to(ROOT)
            backup_path = backup_dir / relative
            shutil.copy2(backup_path, path)
            print(f"[RESTORE] {relative}")

        print()
        print("[STOP] Sistem değişiklik öncesi duruma döndürüldü.")
        print(f"[BACKUP] {backup_dir.relative_to(ROOT)}")
        return 1

    print()
    print("============================================================")
    print(" SUCCESS")
    print("============================================================")
    print("4 hedef dosya syntax olarak doğrulandı.")
    print("Live engine çalıştırılmadı.")
    print(".env değiştirilmedi.")
    print("DB değiştirilmedi.")
    print("logs değiştirilmedi.")
    print("runtime değiştirilmedi.")
    print()
    print(f"BACKUP: {backup_dir.relative_to(ROOT)}")
    print("============================================================")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
