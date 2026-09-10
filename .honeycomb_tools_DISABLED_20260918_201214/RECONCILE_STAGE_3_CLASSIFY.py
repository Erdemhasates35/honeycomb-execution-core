#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import subprocess
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path.cwd()
OUT = ROOT / ".honeycomb_recovery" / "20260913T183750Z"
REPORT = OUT / "STAGE_3_THREE_WAY_CLASSIFICATION.txt"

BASE = "5488b68b11bece74a75cba7c2402d6611513c0d8"
LOCAL = "HEAD"
REMOTE = "origin/main"

KEY = [
    ".gitignore",
    ".env.example",
    "alpha_core.py",
    "extreme_scanner_engine.py",
    "extreme_scanner_omega.py",
    "helix_sovereign_pro.py",
    "live/__init__.py",
    "live/kernel.py",
    "live/kernel_hardened_sign.py",
    "orchestrator/control_plane.py",
    "orchestrator/registry.json",
    "profit_economics.py",
    "quantum_nexus_v3_monolithic.py",
    "sovereign_live.py",
    "sovereign_parliament_engine.py",
    "adaptive_profit_runtime.py",
]

def git(*args):
    p = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return p.returncode, p.stdout.strip()

def exists(ref, path):
    rc, _ = git("cat-file", "-e", f"{ref}:{path}")
    return rc == 0

def blob(ref, path):
    rc, out = git("rev-parse", f"{ref}:{path}")
    return out if rc == 0 else None

def working_hash(path):
    p = ROOT / path
    if not p.exists():
        return None

    rc, out = git("hash-object", str(p))
    return out if rc == 0 else None

def classify(path):
    b = blob(BASE, path)
    l = blob(LOCAL, path)
    r = blob(REMOTE, path)
    w = working_hash(path)

    if b == l == r:
        state = "UNCHANGED_FROM_BASE"

    elif b == l and r != b:
        state = "GITHUB_ONLY_CHANGE"

    elif b == r and l != b:
        state = "LOCAL_COMMIT_ONLY_CHANGE"

    elif l == r and l != b:
        state = "BOTH_SAME_NEW_CHANGE"

    elif b != l and b != r and l != r:
        state = "BOTH_DIVERGED"

    elif l is None and r is not None:
        state = "LOCAL_MISSING_GITHUB_HAS"

    elif l is not None and r is None:
        state = "GITHUB_MISSING_LOCAL_HAS"

    elif l is None and r is None:
        state = "BOTH_MISSING"

    else:
        state = "SPECIAL"

    if w != l:
        if w is None:
            work = "WORKTREE_MISSING_OR_UNTRACKED_STATE"
        else:
            work = "WORKTREE_MODIFIED"
    else:
        work = "WORKTREE_EQUALS_HEAD"

    return b, l, r, w, state, work

lines = []

def out(s=""):
    lines.append(str(s))

out("=" * 80)
out("HONEYCOMB — STAGE 3 THREE-WAY CLASSIFICATION")
out("=" * 80)
out(f"UTC: {datetime.now(timezone.utc).isoformat()}")
out(f"BASE  : {BASE}")
out(f"LOCAL : {LOCAL}")
out(f"GITHUB: {REMOTE}")
out("READ ONLY — NO MERGE / CHECKOUT / RESTORE / DELETE")
out("")

out("=== KEY FILES ===")

for path in KEY:
    b, l, r, w, state, work = classify(path)

    out("")
    out(f"[{path}]")
    out(f"CLASSIFICATION = {state}")
    out(f"WORKTREE       = {work}")
    out(f"BASE          = {b}")
    out(f"LOCAL_HEAD    = {l}")
    out(f"GITHUB_MAIN   = {r}")
    out(f"WORKTREE_HASH = {w}")

out("")
out("=== ALL TRACKED FILES: LOCAL vs GITHUB ===")

rc, diff = git("diff", "--name-status", LOCAL, REMOTE)
if diff:
    for line in diff.splitlines():
        parts = line.split("\t")
        status = parts[0]
        path = parts[-1]

        if any(x in path for x in [
            ".venv/",
            ".git/",
            ".honeycomb_recovery/",
            "__pycache__/",
            "node_modules/",
        ]):
            continue

        out(f"{status}\t{path}")

out("")
out("=== LOCAL WORKTREE MODIFICATIONS ===")

rc, status = git("status", "--short")

if status:
    for line in status.splitlines():
        path = line[3:] if len(line) > 3 else line

        if any(x in path for x in [
            ".venv/",
            ".honeycomb_recovery/",
            "__pycache__/",
            "node_modules/",
        ]):
            continue

        out(line)

out("")
out("=== CRITICAL DECISION SET ===")

for path in KEY:
    b, l, r, w, state, work = classify(path)

    if state in {
        "BOTH_DIVERGED",
        "LOCAL_COMMIT_ONLY_CHANGE",
        "GITHUB_ONLY_CHANGE",
        "GITHUB_MISSING_LOCAL_HAS",
        "LOCAL_MISSING_GITHUB_HAS",
        "SPECIAL",
    }:
        out(
            f"{path} :: {state} :: {work}"
        )

out("")
out("=" * 80)
out("END STAGE 3")
out("=" * 80)

REPORT.write_text(
    "\n".join(lines) + "\n",
    encoding="utf-8"
)

print("\n".join(lines))
print("")
print(f"[REPORT] {REPORT}")
