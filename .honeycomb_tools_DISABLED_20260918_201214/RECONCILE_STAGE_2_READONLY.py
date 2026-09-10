#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path.cwd()
OUT = ROOT / ".honeycomb_recovery" / "20260913T183750Z"
REPORT = OUT / "STAGE_2_READONLY_REPORT.txt"

EXCLUDE_DIRS = {
    ".git",
    ".venv",
    ".honeycomb_recovery",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
}

INTERESTING_EXT = {
    ".py", ".sh", ".bash", ".js", ".ts", ".tsx", ".json",
    ".yaml", ".yml", ".toml", ".ini", ".env", ".md"
}

KEY_FILES = [
    "alpha_core.py",
    "extreme_scanner_engine.py",
    "extreme_scanner_omega.py",
    "helix_sovereign_pro.py",
    "live/__init__.py",
    "live/kernel.py",
    "live/kernel_hardened_sign.py",
    "orchestrator/registry.json",
    "quantum_nexus_v3_monolithic.py",
    "sovereign_live.py",
    "sovereign_parliament_engine.py",
    ".gitignore",
]

def run(*args):
    p = subprocess.run(
        list(args),
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return p.returncode, p.stdout

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def git(*args):
    return run("git", *args)[1]

lines = []
def emit(s=""):
    lines.append(str(s))

emit("=" * 78)
emit("HONEYCOMB — RECONCILIATION STAGE 2 READ-ONLY")
emit("=" * 78)
emit(f"UTC: {datetime.now(timezone.utc).isoformat()}")
emit(f"ROOT: {ROOT}")
emit("NO SOURCE FILES WILL BE MODIFIED")
emit("")

emit("=== COMMITS ===")
emit("LOCAL HEAD")
emit(git("rev-parse", "HEAD").strip())
emit("GITHUB MAIN")
emit(git("rev-parse", "origin/main").strip())
emit("MERGE BASE")
emit(git("merge-base", "HEAD", "origin/main").strip())
emit("")

emit("=== LOCAL WORKTREE STATUS ===")
emit(git("status", "--short"))
emit("")

emit("=== LOCAL vs GITHUB — NAME/STATUS ===")
emit(git("diff", "--name-status", "HEAD", "origin/main"))
emit("")

emit("=== LOCAL vs GITHUB — STAT ===")
emit(git("diff", "--stat", "HEAD", "origin/main"))
emit("")

emit("=== COMMON ANCESTOR -> LOCAL ===")
emit(git("diff", "--name-status",
         "5488b68b11bece74a75cba7c2402d6611513c0d8",
         "HEAD"))
emit("")

emit("=== COMMON ANCESTOR -> GITHUB ===")
emit(git("diff", "--name-status",
         "5488b68b11bece74a75cba7c2402d6611513c0d8",
         "origin/main"))
emit("")

emit("=== KEY FILE THREE-WAY STATUS ===")
for f in KEY_FILES:
    emit("")
    emit(f"--- {f} ---")

    p = ROOT / f
    local_exists = p.exists()

    rc, out = run(
        "git", "cat-file", "-e",
        f"HEAD:{f}"
    )
    local_head_exists = rc == 0

    rc, out = run(
        "git", "cat-file", "-e",
        f"origin/main:{f}"
    )
    github_exists = rc == 0

    rc, out = run(
        "git", "cat-file", "-e",
        f"5488b68b11bece74a75cba7c2402d6611513c0d8:{f}"
    )
    base_exists = rc == 0

    emit(f"working_tree_exists={local_exists}")
    emit(f"local_HEAD_exists={local_head_exists}")
    emit(f"github_main_exists={github_exists}")
    emit(f"merge_base_exists={base_exists}")

    if local_exists:
        try:
            emit(f"working_tree_sha256={sha256(p)}")
        except Exception as e:
            emit(f"working_tree_sha256=ERROR {e}")

    if local_head_exists:
        emit(
            "HEAD_SHA256=" +
            git("rev-parse", f"HEAD:{f}").strip()
        )

    if github_exists:
        emit(
            "GITHUB_BLOB_SHA256=" +
            git("rev-parse", f"origin/main:{f}").strip()
        )

    if base_exists:
        emit(
            "BASE_BLOB_SHA256=" +
            git(
                "rev-parse",
                f"5488b68b11bece74a75cba7c2402d6611513c0d8:{f}"
            ).strip()
        )

emit("")
emit("=== CONFLICT MARKER CHECK — WORKTREE SOURCE ONLY ===")

count = 0
for root, dirs, files in os.walk(ROOT):
    dirs[:] = [
        d for d in dirs
        if d not in EXCLUDE_DIRS
    ]

    for name in files:
        path = Path(root) / name

        if path.suffix.lower() not in INTERESTING_EXT:
            continue

        try:
            text = path.read_text(
                encoding="utf-8",
                errors="ignore"
            )
        except Exception:
            continue

        markers = {
            "<<<<<<<": text.count("<<<<<<<"),
            "=======": text.count("======="),
            ">>>>>>>": text.count(">>>>>>>"),
        }

        if any(markers.values()):
            count += 1
            emit(
                f"{path.relative_to(ROOT)} "
                f"<<<<<<<={markers['<<<<<<<']} "
                f"======={markers['=======']} "
                f">>>>>>>={markers['>>>>>>>']}"
            )

emit(f"MARKER_FILES={count}")
emit("")

emit("=== /tmp REFERENCE CHECK — SOURCE ONLY ===")
tmp_hits = 0

for root, dirs, files in os.walk(ROOT):
    dirs[:] = [
        d for d in dirs
        if d not in EXCLUDE_DIRS
    ]

    for name in files:
        path = Path(root) / name

        if path.suffix.lower() not in INTERESTING_EXT:
            continue

        try:
            text = path.read_text(
                encoding="utf-8",
                errors="ignore"
            )
        except Exception:
            continue

        if "/tmp/" in text or "/tmp" in text:
            tmp_hits += 1
            emit(str(path.relative_to(ROOT)))

emit(f"TMP_REFERENCE_FILES={tmp_hits}")
emit("")

emit("=== KEY FILE LINE COUNTS ===")
for f in KEY_FILES:
    p = ROOT / f
    if p.exists():
        try:
            n = len(
                p.read_text(
                    encoding="utf-8",
                    errors="ignore"
                ).splitlines()
            )
            emit(f"{f}: {n}")
        except Exception as e:
            emit(f"{f}: ERROR {e}")
    else:
        emit(f"{f}: MISSING")

emit("")
emit("=" * 78)
emit("END STAGE 2 — READ ONLY")
emit("=" * 78)

REPORT.write_text(
    "\n".join(lines) + "\n",
    encoding="utf-8"
)

print("\n".join(lines))
print("")
print(f"[REPORT] {REPORT}")
