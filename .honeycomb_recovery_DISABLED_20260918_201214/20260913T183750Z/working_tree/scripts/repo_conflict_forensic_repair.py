#!/usr/bin/env python3
from __future__ import annotations

import ast
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
BACKUP = ROOT / "backups" / f"conflict_forensic_{STAMP}"

SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "backups",
    "node_modules",
    ".next",
    "runtime",
}

TEXT_EXT = {
    ".py", ".sh", ".bash", ".js", ".jsx", ".ts", ".tsx",
    ".json", ".yaml", ".yml", ".toml", ".md", ".txt",
    ".env.example", ".service"
}

CRITICAL = [
    Path("alpha_core.py"),
    Path("sovereign_parliament_engine.py"),
    Path("extreme_scanner_omega.py"),
    Path("extreme_scanner_engine.py"),
    Path("live/__init__.py"),
    Path("live/kernel.py"),
    Path("live/kernel_hardened_sign.py"),
    Path("helix_sovereign_pro.py"),
]

def should_skip(p: Path) -> bool:
    return any(part in SKIP_DIRS for part in p.parts)

def is_text_file(p: Path) -> bool:
    if p.suffix in TEXT_EXT:
        return True
    try:
        data = p.read_bytes()
        return b"\x00" not in data
    except Exception:
        return False

def conflict_lines(text: str):
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if s.startswith("<<<<<<<") or s == "=======" or s.startswith(">>>>>>>"):
            out.append((n, line))
    return out

def backup_file(p: Path):
    rel = p.relative_to(ROOT)
    dst = BACKUP / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(p, dst)

def scan():
    findings = {}
    for p in ROOT.rglob("*"):
        if not p.is_file() or should_skip(p) or not is_text_file(p):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        c = conflict_lines(text)
        if c:
            findings[p] = c
    return findings

def syntax_check(p: Path) -> bool:
    if p.suffix != ".py":
        return True
    try:
        ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        return True
    except Exception:
        return False

def safe_python_conflict_repair(p: Path) -> bool:
    """
    Deliberately conservative:
    - If a conflict has exactly one side that parses, select that side.
    - If both sides parse, DO NOT guess.
    - If neither parses, DO NOT modify.
    """
    text = p.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines(keepends=True)

    if not conflict_lines(text):
        return False

    output = []
    i = 0
    changed = False

    while i < len(lines):
        if not lines[i].lstrip().startswith("<<<<<<<"):
            output.append(lines[i])
            i += 1
            continue

        start = i
        i += 1
        ours = []

        while i < len(lines) and lines[i].strip() != "=======":
            ours.append(lines[i])
            i += 1

        if i >= len(lines):
            return False

        i += 1
        theirs = []

        while i < len(lines) and not lines[i].lstrip().startswith(">>>>>>>"):
            theirs.append(lines[i])
            i += 1

        if i >= len(lines):
            return False

        i += 1

        # Test complete candidate files, not fragments.
        prefix = "".join(output)
        suffix = "".join(lines[i:])

        candidate_ours = prefix + "".join(ours) + suffix
        candidate_theirs = prefix + "".join(theirs) + suffix

        ok_ours = False
        ok_theirs = False

        try:
            ast.parse(candidate_ours)
            ok_ours = True
        except Exception:
            pass

        try:
            ast.parse(candidate_theirs)
            ok_theirs = True
        except Exception:
            pass

        if ok_ours and not ok_theirs:
            output.extend(ours)
            changed = True
        elif ok_theirs and not ok_ours:
            output.extend(theirs)
            changed = True
        else:
            # Ambiguous = NEVER guess.
            return False

    if changed:
        backup_file(p)
        p.write_text("".join(output), encoding="utf-8")
        return True

    return False

def main():
    print(f"===== HONEYCOMB CONFLICT FORENSIC REPAIR {STAMP} =====")
    print(f"ROOT={ROOT}")
    print(f"BACKUP={BACKUP}")

    findings = scan()

    if not findings:
        print("MERGE_MARKERS=0")
        return 0

    print(f"CONFLICT_FILES={len(findings)}")

    repaired = []
    ambiguous = []

    for p, hits in findings.items():
        print(f"\nCONFLICT {p}")
        for n, line in hits:
            print(f"  line {n}: {line}")

        if p.suffix == ".py":
            try:
                if safe_python_conflict_repair(p):
                    repaired.append(str(p))
                    print("  -> AUTO_REPAIRED=SAFE_SINGLE_PARSE")
                else:
                    ambiguous.append(str(p))
                    print("  -> AMBIGUOUS=NO_AUTOMATIC_MERGE")
            except Exception as exc:
                ambiguous.append(str(p))
                print(f"  -> REPAIR_ERROR={type(exc).__name__}: {exc}")
        else:
            ambiguous.append(str(p))
            print("  -> AMBIGUOUS=NON_PYTHON")

    print("\n===== RESULT =====")
    print(f"REPAIRED={len(repaired)}")
    print(f"AMBIGUOUS={len(ambiguous)}")

    if ambiguous:
        print("\nAMBIGUOUS FILES:")
        for x in ambiguous:
            print(x)

        print("\nNO LIVE ENGINE STARTED.")
        return 21

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
