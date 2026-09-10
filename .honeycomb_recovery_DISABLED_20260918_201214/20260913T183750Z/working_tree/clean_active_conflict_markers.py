#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
HONEYCOMB — ACTIVE TREE CONFLICT MARKER CLEANER

Bilimsel/teknik kapsam:
- Sadece lexical conflict-marker satırlarını kaldırır.
- Kod bloklarını seçmez.
- Kod satırlarını değiştirmez.
- Indentation düzeltmez.
- AST refactor yapmaz.
- .env / DB / runtime / logs / backups değiştirmez.
- Git commit/push yapmaz.
- Live engine çalıştırmaz.

Kaynak bütünlüğü:
Her değişiklikten önce dosyanın SHA-256 hash'i alınır
ve orijinal dosya backups/ altında saklanır.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent

STAMP = time.strftime("%Y%m%d_%H%M%S")
BACKUP_ROOT = ROOT / "backups" / f"active_marker_cleanup_{STAMP}"


# ============================================================
# ASLA TARANMAYACAK KLASÖRLER
# ============================================================

EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    "node_modules",

    # Tarihsel / forensic kanıtlar
    "backups",

    # Runtime
    "runtime",
    "logs",
    ".honeycomb_runtime",
}


# ============================================================
# ASLA DEĞİŞTİRİLMEYECEK DOSYALAR
# ============================================================

EXCLUDED_FILES = {
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
    ".env.test",
}


EXCLUDED_SUFFIXES = {
    ".db",
    ".db-shm",
    ".db-wal",
    ".sqlite",
    ".sqlite3",
    ".pyc",
    ".so",
    ".dll",
    ".exe",
    ".bin",
    ".zip",
    ".tar",
    ".gz",
    ".xz",
    ".7z",
}


# ============================================================
# GIT CONFLICT MARKER TANIMLARI
# ============================================================

MARKER_PATTERNS = [
    # Standart Git:
    re.compile(r"^\s*<{7}.*$"),
    re.compile(r"^\s*={7}\s*$"),
    re.compile(r"^\s*>{7}.*$"),

    # Honeycomb özel:
    re.compile(
        r"^\s*#?\s*HONEYCOMB_CONFLICT_MARKER\s+<{7}.*$"
    ),
    re.compile(
        r"^\s*#?\s*HONEYCOMB_CONFLICT_MARKER\s+>{7}.*$"
    ),
]


def marker_type(line: str):
    s = line.strip()

    if "HONEYCOMB_CONFLICT_MARKER" in s:
        if "<<<<<<<" in s:
            return "HONEYCOMB <<<<<<<"

        if ">>>>>>>" in s:
            return "HONEYCOMB >>>>>>>"

    if s.startswith("<<<<<<<"):
        return "<<<<<<<"

    if s == "=======":
        return "======="

    if s.startswith(">>>>>>>"):
        return ">>>>>>>"

    return None


def is_marker(line: str) -> bool:
    for pattern in MARKER_PATTERNS:
        if pattern.match(line.rstrip("\r\n")):
            return True

    return False


def sha256(path: Path) -> str:
    h = hashlib.sha256()

    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)

            if not chunk:
                break

            h.update(chunk)

    return h.hexdigest()


def text_file(path: Path) -> bool:

    try:
        data = path.read_bytes()[:1024 * 1024]
    except Exception:
        return False

    # Binary safety
    if b"\x00" in data:
        return False

    try:
        data.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def excluded(path: Path) -> bool:

    if path.name in EXCLUDED_FILES:
        return True

    if path.name.startswith(".env"):
        return True

    if path.suffix.lower() in EXCLUDED_SUFFIXES:
        return True

    try:
        rel = path.relative_to(ROOT)
    except ValueError:
        return True

    for part in rel.parts:
        if part in EXCLUDED_DIRS:
            return True

    return False


def iter_active_files():

    for dirpath, dirnames, filenames in os.walk(ROOT):

        # Çok önemli:
        # backups burada tamamen budanıyor.
        dirnames[:] = [
            d
            for d in dirnames
            if d not in EXCLUDED_DIRS
        ]

        for filename in filenames:

            path = Path(dirpath) / filename

            if excluded(path):
                continue

            if path == Path(__file__).resolve():
                continue

            yield path


def backup(path: Path) -> Path:

    relative = path.relative_to(ROOT)

    destination = BACKUP_ROOT / relative

    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    shutil.copy2(
        path,
        destination,
    )

    return destination


def main():

    print()
    print("=" * 78)
    print(" HONEYCOMB ACTIVE CONFLICT MARKER CLEANER")
    print("=" * 78)
    print()

    print("ROOT   =", ROOT)
    print("BACKUP =", BACKUP_ROOT)
    print()

    print("SCOPE:")
    print("  ACTIVE WORK TREE ONLY")
    print("  backups/            = EXCLUDED")
    print("  .git/               = EXCLUDED")
    print("  .env*               = EXCLUDED")
    print("  DB                  = EXCLUDED")
    print("  runtime             = EXCLUDED")
    print("  logs                = EXCLUDED")
    print()

    scanned = 0
    text_scanned = 0
    changed = 0
    removed = 0

    counters = {
        "<<<<<<<": 0,
        "=======": 0,
        ">>>>>>>": 0,
        "HONEYCOMB <<<<<<<": 0,
        "HONEYCOMB >>>>>>>": 0,
    }

    failures = []

    files = list(iter_active_files())

    print("ACTIVE_FILES =", len(files))
    print()

    # ========================================================
    # CLEAN
    # ========================================================

    for path in files:

        scanned += 1

        if not text_file(path):
            continue

        text_scanned += 1

        try:
            original = path.read_text(
                encoding="utf-8",
                errors="strict",
            )
        except Exception as e:
            failures.append(
                (str(path), "READ", repr(e))
            )
            continue

        lines = original.splitlines(
            keepends=True
        )

        new_lines = []
        removed_here = []

        for lineno, line in enumerate(
            lines,
            start=1,
        ):

            kind = marker_type(line)

            if kind is not None:

                removed_here.append(
                    (
                        lineno,
                        kind,
                        line.rstrip("\r\n"),
                    )
                )

                continue

            new_lines.append(line)

        if not removed_here:
            continue

        print("CLEAN:", path)

        # ----------------------------------------------------
        # BACKUP FIRST
        # ----------------------------------------------------

        try:
            original_hash = sha256(path)
            backup_path = backup(path)
        except Exception as e:
            failures.append(
                (str(path), "BACKUP", repr(e))
            )

            print("  BACKUP FAILED")
            continue

        # ----------------------------------------------------
        # WRITE ONLY THE CLEANED TEXT
        # ----------------------------------------------------

        cleaned = "".join(new_lines)

        try:
            path.write_text(
                cleaned,
                encoding="utf-8",
                newline="",
            )
        except Exception as e:
            failures.append(
                (str(path), "WRITE", repr(e))
            )

            print("  WRITE FAILED")
            continue

        # ----------------------------------------------------
        # IMMEDIATE VERIFICATION
        # ----------------------------------------------------

        try:
            verify = path.read_text(
                encoding="utf-8",
                errors="strict",
            )
        except Exception as e:
            failures.append(
                (str(path), "VERIFY_READ", repr(e))
            )
            continue

        remaining_here = []

        for lineno, line in enumerate(
            verify.splitlines(),
            start=1,
        ):

            kind = marker_type(line)

            if kind is not None:
                remaining_here.append(
                    (
                        lineno,
                        kind,
                        line,
                    )
                )

        if remaining_here:

            failures.append(
                (
                    str(path),
                    "MARKER_REMAINS",
                    repr(remaining_here),
                )
            )

            print(
                "  WARNING: MARKER STILL PRESENT"
            )

            continue

        changed += 1
        removed += len(removed_here)

        for _, kind, _ in removed_here:
            counters[kind] += 1

        print(
            "  REMOVED =",
            len(removed_here),
        )

        print(
            "  BACKUP  =",
            backup_path,
        )

        print(
            "  SHA256  =",
            original_hash,
        )

    # ========================================================
    # FINAL ACTIVE-TREE SCAN
    # ========================================================

    remaining = []

    for path in iter_active_files():

        if not text_file(path):
            continue

        try:
            text = path.read_text(
                encoding="utf-8",
                errors="strict",
            )
        except Exception:
            continue

        for lineno, line in enumerate(
            text.splitlines(),
            start=1,
        ):

            kind = marker_type(line)

            if kind is not None:
                remaining.append(
                    (
                        str(path),
                        lineno,
                        kind,
                        line,
                    )
                )

    # ========================================================
    # FINAL REPORT
    # ========================================================

    print()
    print("=" * 78)
    print(" FINAL RESULT")
    print("=" * 78)

    print("FILES_SCANNED      =", scanned)
    print("TEXT_FILES_SCANNED =", text_scanned)
    print("CHANGED_FILES      =", changed)
    print("REMOVED_MARKERS    =", removed)

    print()
    print("MARKER BREAKDOWN")

    for key, value in counters.items():
        print(
            "  %-24s = %d"
            % (key, value)
        )

    print()
    print(
        "REMAINING_MARKER_LINES =",
        len(remaining),
    )

    if remaining:

        print()
        print("REMAINING ACTIVE MARKERS")
        print("-" * 78)

        for path, lineno, kind, line in remaining:
            print(
                "%s:%d [%s] %s"
                % (
                    path,
                    lineno,
                    kind,
                    line,
                )
            )

    print()
    print("BACKUP_DIR =", BACKUP_ROOT)

    print()
    print("SAFETY")
    print("ENV_MODIFIED        = NO")
    print("DATABASE_MODIFIED   = NO")
    print("RUNTIME_MODIFIED    = NO")
    print("BACKUPS_MODIFIED    = NO")
    print("LIVE_STARTED        = NO")
    print("LIVE_ORDER_CALLED   = NO")
    print("GIT_COMMIT          = NO")
    print("GIT_PUSH            = NO")

    print()

    if failures:

        print("FAILURES =", len(failures))

        for failure in failures:
            print(failure)

    else:
        print("FAILURES = 0")

    print()

    if remaining:
        print(
            "STATUS = ACTIVE CONFLICT MARKERS REMAIN"
        )
        return 2

    print(
        "STATUS = ACTIVE CONFLICT MARKERS = 0"
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
