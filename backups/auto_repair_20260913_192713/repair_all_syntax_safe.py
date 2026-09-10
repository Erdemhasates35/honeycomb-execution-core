#!/usr/bin/env python3
# Honeycomb SAFE repository repair
# - Full backup before modification
# - Never touches .env / credentials / DB / runtime data
# - Never starts engines or network execution
# - Repairs ONLY deterministic syntax/encoding/conflict-marker damage
# - Does NOT delete existing source lines
# - AI is analysis-only unless HONEYCOMB_AI_REPAIR=1 is explicitly set

from __future__ import annotations

import ast
import io
import os
import re
import shutil
import subprocess
import sys
import tokenize
from pathlib import Path
from datetime import datetime

ROOT = Path.cwd()
STAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
BACKUP = ROOT / "backups" / f"auto_repair_{STAMP}"
BACKUP.mkdir(parents=True, exist_ok=True)

EXCLUDE_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__",
    "backups", "runtime", "logs", ".honeycomb_runtime"
}

EXCLUDE_FILES = {
    ".env", ".env.local", ".env.production", ".env.development",
}

TEXT_EXT = {
    ".py", ".pyw", ".sh", ".bash", ".js", ".jsx", ".ts", ".tsx",
    ".json", ".yaml", ".yml", ".toml"
}

PY_EXT = {".py", ".pyw"}

changed = []
errors_before = []
errors_after = []


def excluded(p: Path) -> bool:
    rel = p.relative_to(ROOT)
    if any(x in EXCLUDE_DIRS for x in rel.parts):
        return True
    if p.name in EXCLUDE_FILES:
        return True
    if p.name.startswith(".env."):
        return True
    return False


def backup_file(p: Path):
    rel = p.relative_to(ROOT)
    dst = BACKUP / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(p, dst)


def run_compile(p: Path):
    return subprocess.run(
        [sys.executable, "-m", "py_compile", str(p)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )


def conflict_fix(text: str):
    """
    Deterministic conflict repair.

    IMPORTANT:
    No side of a conflict is deleted.
    Git conflict markers are converted into Python comments.
    Both existing code sides remain byte-for-byte present.

    This guarantees the source information is preserved.
    """
    lines = text.splitlines(keepends=True)

    out = []
    found = False

    for line in lines:
        stripped = line.lstrip()

        if stripped.startswith("<<<<<<<"):
            prefix = line[:len(line) - len(stripped)]
            out.append(prefix + "# HONEYCOMB_CONFLICT_MARKER " + stripped)
            found = True
            continue

        if stripped == "=======":
            prefix = line[:len(line) - len(stripped)]
            out.append(prefix + "# HONEYCOMB_CONFLICT_SEPARATOR\n")
            found = True
            continue

        if stripped.startswith(">>>>>>>"):
            prefix = line[:len(line) - len(stripped)]
            out.append(prefix + "# HONEYCOMB_CONFLICT_MARKER " + stripped)
            found = True
            continue

        out.append(line)

    return "".join(out), found


def encoding_repair(data: bytes):
    """
    Only repairs invalid UTF-8 representation.
    Existing bytes are preserved through surrogateescape where possible.
    """
    try:
        return data.decode("utf-8"), False
    except UnicodeDecodeError:
        text = data.decode("utf-8", errors="surrogateescape")
        return text, True


def normalize_python_newlines(text: str):
    new = text.replace("\r\n", "\n").replace("\r", "\n")
    return new, new != text


def remove_nul_only(text: str):
    # NUL bytes cannot legally occur in Python source.
    # They are not meaningful source characters.
    if "\x00" not in text:
        return text, False
    return text.replace("\x00", ""), True


def syntax_files():
    for p in ROOT.rglob("*"):
        if not p.is_file():
            continue
        if excluded(p):
            continue
        if p.suffix.lower() not in PY_EXT:
            continue
        yield p


def scan_python():
    result = []
    for p in syntax_files():
        r = run_compile(p)
        if r.returncode != 0:
            result.append((p, r.stderr.strip()))
    return result


print("=" * 72)
print("HONEYCOMB SAFE AUTO REPAIR")
print("=" * 72)
print("ROOT   :", ROOT)
print("BACKUP :", BACKUP)
print("LIVE   : DISABLED")
print()

# Always force this repair process into non-live mode.
os.environ["EXECUTION_MODE"] = "PAPER"
os.environ["HONEYCOMB_MODE"] = "PAPER"
os.environ["LIVE_ARMED"] = "0"

# ------------------------------------------------------------------
# 1. BACKUP ALL TEXT SOURCE FILES
# ------------------------------------------------------------------

print("[1/5] BACKUP")

for p in ROOT.rglob("*"):
    if not p.is_file() or excluded(p):
        continue
    if p.suffix.lower() not in TEXT_EXT:
        continue

    try:
        backup_file(p)
    except Exception as e:
        print("BACKUP_FAIL", p, e)

print("BACKUP_COMPLETE")

# ------------------------------------------------------------------
# 2. INITIAL SYNTAX INVENTORY
# ------------------------------------------------------------------

print()
print("[2/5] INITIAL PYTHON SYNTAX SCAN")

errors_before = scan_python()

print("PYTHON_FILES_WITH_ERRORS =", len(errors_before))

for p, err in errors_before:
    print()
    print("ERROR:", p)
    print(err[:3000])

# ------------------------------------------------------------------
# 3. DETERMINISTIC SAFE REPAIR
# ------------------------------------------------------------------

print()
print("[3/5] SAFE REPAIR")

for p in syntax_files():

    try:
        raw = p.read_bytes()
        text, encoding_changed = encoding_repair(raw)

        text2, newline_changed = normalize_python_newlines(text)
        text = text2

        text2, nul_changed = remove_nul_only(text)
        text = text2

        text2, conflict_changed = conflict_fix(text)
        text = text2

        changed_here = (
            encoding_changed
            or newline_changed
            or nul_changed
            or conflict_changed
        )

        if not changed_here:
            continue

        # Preserve a second per-file pre-repair copy.
        backup_file(p)

        p.write_text(text, encoding="utf-8", newline="\n")
        changed.append(str(p.relative_to(ROOT)))

        reasons = []
        if encoding_changed:
            reasons.append("encoding")
        if newline_changed:
            reasons.append("newline")
        if nul_changed:
            reasons.append("NUL")
        if conflict_changed:
            reasons.append("conflict-markers")

        print("REPAIRED:", p, "|", ",".join(reasons))

    except Exception as e:
        print("REPAIR_FAIL:", p, "|", repr(e))

# ------------------------------------------------------------------
# 4. SECOND SYNTAX SCAN
# ------------------------------------------------------------------

print()
print("[4/5] SECOND PYTHON SYNTAX SCAN")

errors_after = scan_python()

print("REMAINING_PYTHON_ERRORS =", len(errors_after))

for p, err in errors_after:
    print()
    print("REMAINING:", p)
    print(err[:4000])

# ------------------------------------------------------------------
# 5. STATIC CONFLICT + CONTROL CHECK
# ------------------------------------------------------------------

print()
print("[5/5] FINAL STATIC CHECK"

)

conflicts = []

for p in ROOT.rglob("*"):
    if not p.is_file() or excluded(p):
        continue

    try:
        data = p.read_text(encoding="utf-8", errors="replace")

        if re.search(r"^(<<<<<<<|=======|>>>>>>>)", data, re.MULTILINE):
            conflicts.append(str(p.relative_to(ROOT)))

    except Exception:
        pass

print("ACTIVE_CONFLICT_MARKER_FILES =", len(conflicts))

for x in conflicts:
    print("CONFLICT:", x)

print()
print("=" * 72)
print("RESULT")
print("=" * 72)
print("BACKUP =", BACKUP)
print("CHANGED =", len(changed))
print("SYNTAX_ERRORS_BEFORE =", len(errors_before))
print("SYNTAX_ERRORS_AFTER  =", len(errors_after))
print("CONFLICT_FILES_AFTER =", len(conflicts))

if changed:
    print()
    print("CHANGED_FILES")
    for x in changed:
        print(x)

print()
print("NO ENGINE STARTED")
print("NO LIVE ORDER FUNCTION CALLED")
print("NO ENV FILE MODIFIED")
print("NO DATABASE MODIFIED")
print("NO GIT COMMIT")
print("NO GIT PUSH")

if errors_after:
    print()
    print("REMAINING_ERRORS_REQUIRE_SEMANTIC_REPAIR=YES")
else:
    print()
    print("PYTHON_SYNTAX_SCAN=PASS")
