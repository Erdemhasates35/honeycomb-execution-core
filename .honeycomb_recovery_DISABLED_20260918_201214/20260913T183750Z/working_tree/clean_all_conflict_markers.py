#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
HONEYCOMB — GLOBAL GIT CONFLICT MARKER CLEANER
================================================

AMAÇ
----
Repository içerisindeki Git merge-conflict ARTIFACT satırlarını temizlemek.

TEMİZLENENLER
-------------

ÖNEMLİ
------
Bu program:
    - kod bloklarını seçmez
    - kod bloklarını birleştirmez
    - fonksiyon silmez
    - satırları dedent etmez
    - syntax düzeltmez
    - .env dosyalarına dokunmaz
    - DB dosyalarına dokunmaz
    - runtime dosyalarına dokunmaz
    - canlı motor çalıştırmaz
    - emir fonksiyonu çağırmaz
    - git commit/push yapmaz

SADECE marker SATIRLARINI kaldırır.

Her değiştirilen dosya önce SHA-256 ile yedeklenir.
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

BACKUP_ROOT = (
    ROOT
    / "backups"
    / ("conflict_marker_cleanup_" + time.strftime("%Y%m%d_%H%M%S"))
)

# ------------------------------------------------------------
# KESİNLİKLE DOKUNULMAYACAKLAR
# ------------------------------------------------------------

EXCLUDED_DIR_NAMES = {
    ".git",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    "node_modules",
    "runtime",
    "logs",
    ".honeycomb_runtime",
}

EXCLUDED_FILE_NAMES = {
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
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".mp4",
    ".mp3",
    ".zip",
    ".tar",
    ".gz",
    ".xz",
    ".7z",
}

# ------------------------------------------------------------
# GIT CONFLICT MARKER REGEX
# ------------------------------------------------------------

MARKER_PATTERNS = [
    re.compile(r"^\s*<{7}(?:.*)?\s*$"),
    re.compile(r"^\s*={7}\s*$"),
    re.compile(r"^\s*>{7}(?:.*)?\s*$"),

    # Honeycomb özel marker'ları
    re.compile(
        r"^\s*#?\s*HONEYCOMB_CONFLICT_MARKER\s+<{7}.*$"
    ),
    re.compile(
        r"^\s*#?\s*HONEYCOMB_CONFLICT_MARKER\s+>{7}.*$"
    ),
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()

    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)

            if not chunk:
                break

            h.update(chunk)

    return h.hexdigest()


def is_excluded(path: Path) -> bool:
    try:
        rel = path.relative_to(ROOT)
    except ValueError:
        return True

    # .env ve türevleri
    if path.name in EXCLUDED_FILE_NAMES:
        return True

    # .env*
    if path.name.startswith(".env"):
        return True

    # klasör kontrolleri
    for part in rel.parts:
        if part in EXCLUDED_DIR_NAMES:
            return True

    # binary / database
    if path.suffix.lower() in EXCLUDED_SUFFIXES:
        return True

    return False


def looks_like_text(path: Path) -> bool:
    """
    Dosyanın tamamını decode etmeye çalışmadan ilk bölümden
    binary dosyaları ayırır.
    """

    try:
        data = path.read_bytes()[:1024 * 1024]
    except Exception:
        return False

    if b"\x00" in data:
        return False

    try:
        data.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def contains_marker(text: str) -> bool:
    for line in text.splitlines():
        for pattern in MARKER_PATTERNS:
            if pattern.match(line):
                return True

    return False


def marker_type(line: str) -> str | None:
    s = line.strip()

    if s.startswith("<<<<<<<"):
        return "<<<<<<<"

    if s == "=======":
        return "======="

    if s.startswith(">>>>>>>"):
        return ">>>>>>>"

    if "HONEYCOMB_CONFLICT_MARKER" in s:
        if "<<<<<<<" in s:
            return "HONEYCOMB <<<<<<<"

        if ">>>>>>>" in s:
            return "HONEYCOMB >>>>>>>"

    return None


def clean_text(text: str):
    output = []
    removed = []

    for lineno, line in enumerate(text.splitlines(keepends=True), 1):

        matched = None

        for pattern in MARKER_PATTERNS:
            if pattern.match(line.rstrip("\r\n")):
                matched = marker_type(line)
                break

        if matched is not None:
            removed.append((lineno, matched, line.rstrip("\r\n")))
            continue

        output.append(line)

    return "".join(output), removed


def backup_file(path: Path) -> Path:
    rel = path.relative_to(ROOT)
    destination = BACKUP_ROOT / rel

    destination.parent.mkdir(parents=True, exist_ok=True)

    shutil.copy2(path, destination)

    return destination


def iter_files():
    for dirpath, dirnames, filenames in os.walk(ROOT):

        # excluded directories
        dirnames[:] = [
            d
            for d in dirnames
            if d not in EXCLUDED_DIR_NAMES
        ]

        for filename in filenames:
            path = Path(dirpath) / filename

            if is_excluded(path):
                continue

            if path == Path(__file__).resolve():
                continue

            yield path


def main():
    print()
    print("=" * 76)
    print(" HONEYCOMB GLOBAL CONFLICT MARKER CLEANUP")
    print("=" * 76)
    print()
    print("ROOT   =", ROOT)
    print("BACKUP =", BACKUP_ROOT)
    print()
    print("MODE   = MARKER-ONLY")
    print("ENV    = EXCLUDED")
    print("DB     = EXCLUDED")
    print("RUNTIME= EXCLUDED")
    print("GIT    = NO COMMIT / NO PUSH")
    print("LIVE   = NEVER STARTED")
    print()

    files_seen = 0
    text_files = 0
    changed_files = 0
    removed_markers = 0

    marker_counter = {
        "<<<<<<<": 0,
        "=======": 0,
        ">>>>>>>": 0,
        "HONEYCOMB <<<<<<<": 0,
        "HONEYCOMB >>>>>>>": 0,
    }

    failures = []

    all_files = list(iter_files())

    print("CANDIDATE_FILES =", len(all_files))
    print()

    for path in all_files:

        files_seen += 1

        if not looks_like_text(path):
            continue

        text_files += 1

        try:
            original = path.read_text(
                encoding="utf-8",
                errors="strict",
            )
        except Exception as e:
            failures.append((str(path), "read", repr(e)))
            continue

        if not contains_marker(original):
            continue

        print("CONFLICT:", path)

        cleaned, removed = clean_text(original)

        if not removed:
            continue

        # ----------------------------------------------------
        # Yedekleme — değişiklikten ÖNCE
        # ----------------------------------------------------

        try:
            backup = backup_file(path)

            original_hash = sha256_file(path)

        except Exception as e:
            failures.append(
                (
                    str(path),
                    "backup",
                    repr(e),
                )
            )

            print("  BACKUP FAILED:", repr(e))
            continue

        # ----------------------------------------------------
        # Dosyayı değiştir
        # ----------------------------------------------------

        try:
            path.write_text(
                cleaned,
                encoding="utf-8",
                newline="",
            )
        except Exception as e:
            failures.append(
                (
                    str(path),
                    "write",
                    repr(e),
                )
            )

            print("  WRITE FAILED:", repr(e))
            continue

        # ----------------------------------------------------
        # Yazma sonrası bütünlük kontrolü
        # ----------------------------------------------------

        try:
            new_text = path.read_text(
                encoding="utf-8",
                errors="strict",
            )
        except Exception as e:
            failures.append(
                (
                    str(path),
                    "verify-read",
                    repr(e),
                )
            )

            continue

        if contains_marker(new_text):
            failures.append(
                (
                    str(path),
                    "marker-remains",
                    "marker still detected",
                )
            )

            print("  WARNING: MARKER STILL EXISTS")
            continue

        changed_files += 1
        removed_markers += len(removed)

        for _, kind, _ in removed:
            marker_counter[kind] = (
                marker_counter.get(kind, 0) + 1
            )

        print(
            "  REMOVED =",
            len(removed),
            "MARKERS",
        )

        print(
            "  BACKUP  =",
            backup,
        )

        print(
            "  SHA256  =",
            original_hash,
        )

    # --------------------------------------------------------
    # FINAL GLOBAL SCAN
    # --------------------------------------------------------

    remaining_files = []
    remaining_markers = []

    for path in iter_files():

        if not looks_like_text(path):
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
            1,
        ):
            kind = marker_type(line)

            if kind is not None:
                remaining_files.append(str(path))
                remaining_markers.append(
                    (
                        str(path),
                        lineno,
                        kind,
                        line,
                    )
                )

    remaining_files = sorted(set(remaining_files))

    # --------------------------------------------------------
    # RAPOR
    # --------------------------------------------------------

    print()
    print("=" * 76)
    print(" FINAL RESULT")
    print("=" * 76)

    print("FILES_SCANNED       =", files_seen)
    print("TEXT_FILES_SCANNED  =", text_files)
    print("CHANGED_FILES       =", changed_files)
    print("REMOVED_MARKERS     =", removed_markers)

    print()
    print("REMOVED BREAKDOWN")

    for key, value in marker_counter.items():
        print(
            "  %-24s = %d"
            % (key, value)
        )

    print()
    print("REMAINING_CONFLICT_FILES =",
          len(remaining_files))

    print(
        "REMAINING_MARKER_LINES   =",
        len(remaining_markers),
    )

    if remaining_markers:

        print()
        print("REMAINING MARKERS")
        print("-" * 76)

        for path, lineno, kind, line in remaining_markers:
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
    print("SAFETY STATUS")
    print("ENV_MODIFIED          = NO")
    print("DATABASE_MODIFIED     = NO")
    print("RUNTIME_MODIFIED      = NO")
    print("LIVE_ENGINE_STARTED   = NO")
    print("LIVE_ORDER_CALLED     = NO")
    print("GIT_COMMIT            = NO")
    print("GIT_PUSH              = NO")

    print()

    if failures:

        print("FAILURES =", len(failures))

        for failure in failures:
            print(failure)

    else:
        print("FAILURES = 0")

    print()

    if remaining_markers:
        print(
            "STATUS = CONFLICT MARKERS STILL REMAIN"
        )
        return 2

    print(
        "STATUS = ALL DETECTED CONFLICT MARKERS CLEAN"
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
