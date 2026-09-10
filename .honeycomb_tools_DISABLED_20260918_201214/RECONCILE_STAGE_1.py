#!/data/data/com.termux/files/usr/bin/python3
# -*- coding: utf-8 -*-

"""
HONEYCOMB — STAGE 1
NON-DESTRUCTIVE LOCAL/GITHUB RECONCILIATION SNAPSHOT

AMAÇ:
    1. Mevcut Termux çalışma ağacını tamamen korumak.
    2. Git metadata'sını değiştirmeden GitHub main'i fetch etmek.
    3. GitHub main'i ayrı snapshot olarak almak.
    4. Local değişiklikleri, staged değişiklikleri ve untracked dosyaları
       raporlamak.
    5. Hiçbir kaynak dosyayı değiştirmemek.
    6. .env, DB, runtime, log ve backup dosyalarına dokunmamak.

KESİNLİKLE YAPMAZ:
    - git reset
    - git clean
    - git checkout
    - git restore
    - rm
    - dosya silme
    - .env değiştirme
    - DB değiştirme
    - kaynak kodu düzeltme
"""

from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile

ROOT = Path.cwd()

STAMP = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

RECOVERY = ROOT / ".honeycomb_recovery" / STAMP
WORKTREE_BACKUP = RECOVERY / "working_tree"
GITHUB_SNAPSHOT = RECOVERY / "github_main"
REPORT = RECOVERY / "RECONCILIATION_REPORT.txt"
MANIFEST = RECOVERY / "LOCAL_MANIFEST.sha256"
STATUS = RECOVERY / "GIT_STATUS.txt"
DIFF_UNSTAGED = RECOVERY / "LOCAL_UNSTAGED.patch"
DIFF_STAGED = RECOVERY / "LOCAL_STAGED.patch"
UNTRACKED = RECOVERY / "UNTRACKED_FILES.txt"

REMOTE = "origin"
REMOTE_BRANCH = "origin/main"

RECOVERY.mkdir(parents=True, exist_ok=True)
WORKTREE_BACKUP.mkdir(parents=True, exist_ok=True)
GITHUB_SNAPSHOT.mkdir(parents=True, exist_ok=True)


def run(cmd, check=False):
    print("\n$ " + " ".join(str(x) for x in cmd))
    p = subprocess.run(
        cmd,
        cwd=str(ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if p.stdout:
        print(p.stdout)
    if check and p.returncode != 0:
        raise RuntimeError(
            "COMMAND FAILED (%d): %s"
            % (p.returncode, " ".join(str(x) for x in cmd))
        )
    return p


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_rel(path):
    try:
        return path.relative_to(ROOT)
    except Exception:
        return path


def should_skip(path):
    rel = safe_rel(path)

    if not rel.parts:
        return True

    # Recovery'nin kendisini tekrar backup içine alma.
    if rel.parts[0] == ".honeycomb_recovery":
        return True

    # Git metadata'sını çalışma ağacı snapshot'ına kopyalamıyoruz.
    if rel.parts[0] == ".git":
        return True

    return False


def copy_worktree():
    """
    Çalışma ağacının .git hariç fiziksel snapshot'ı.
    Hiçbir kaynak dosya değiştirilmez.
    """
    print("\n=== LOCAL WORKTREE SNAPSHOT ===")

    count = 0
    errors = []

    for src in ROOT.rglob("*"):
        if should_skip(src):
            continue

        try:
            rel = src.relative_to(ROOT)
        except Exception:
            continue

        dst = WORKTREE_BACKUP / rel

        try:
            if src.is_symlink():
                dst.parent.mkdir(parents=True, exist_ok=True)

                if dst.exists() or dst.is_symlink():
                    dst.unlink()

                dst.symlink_to(os.readlink(src))
                count += 1

            elif src.is_dir():
                dst.mkdir(parents=True, exist_ok=True)

            elif src.is_file():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                count += 1

        except Exception as e:
            errors.append("%s :: %s" % (src, e))

    print("[SNAPSHOT FILES]", count)

    if errors:
        print("[SNAPSHOT ERRORS]", len(errors))
        for e in errors[:50]:
            print(" ", e)

    return errors


def write_manifest():
    print("\n=== LOCAL SHA256 MANIFEST ===")

    count = 0

    with MANIFEST.open("w", encoding="utf-8") as out:
        for p in sorted(WORKTREE_BACKUP.rglob("*")):
            if not p.is_file():
                continue

            try:
                digest = sha256(p)
                rel = p.relative_to(WORKTREE_BACKUP)
                out.write("%s  %s\n" % (digest, rel))
                count += 1
            except Exception as e:
                out.write("ERROR %s :: %s\n" % (p, e))

    print("[MANIFEST FILES]", count)


def git_state():
    print("\n=== GIT STATE BEFORE FETCH ===")

    status = run(["git", "status", "--short"])

    STATUS.write_text(
        status.stdout or "",
        encoding="utf-8",
    )

    unstaged = run(["git", "diff", "--no-ext-diff"])

    DIFF_UNSTAGED.write_text(
        unstaged.stdout or "",
        encoding="utf-8",
    )

    staged = run(["git", "diff", "--cached", "--no-ext-diff"])

    DIFF_STAGED.write_text(
        staged.stdout or "",
        encoding="utf-8",
    )

    untracked = run(
        [
            "git",
            "ls-files",
            "--others",
            "--exclude-standard",
        ]
    )

    UNTRACKED.write_text(
        untracked.stdout or "",
        encoding="utf-8",
    )

    print("\n[UNSTAGED PATCH]", len(unstaged.stdout or ""))
    print("[STAGED PATCH]", len(staged.stdout or ""))
    print("[UNTRACKED LIST]", len(untracked.stdout or ""))


def git_metadata():
    print("\n=== GIT METADATA ===")

    head = run(["git", "rev-parse", "HEAD"])
    branch = run(["git", "branch", "--show-current"])
    origin = run(["git", "remote", "get-url", "origin"])
    merge_base = run(
        [
            "git",
            "merge-base",
            "HEAD",
            REMOTE_BRANCH,
        ]
    )

    return {
        "local_head": (head.stdout or "").strip(),
        "local_branch": (branch.stdout or "").strip(),
        "origin_url": (origin.stdout or "").strip(),
        "merge_base_before_fetch": (merge_base.stdout or "").strip(),
    }


def fetch_github():
    print("\n=== GITHUB FETCH — NO CHECKOUT ===")

    # SADECE remote objelerini indirir.
    # Working tree'ye dokunmaz.
    p = run(
        [
            "git",
            "fetch",
            "--prune",
            "origin",
            "main",
        ],
        check=True,
    )

    return p


def github_metadata():
    print("\n=== GITHUB MAIN METADATA ===")

    remote_head = run(
        ["git", "rev-parse", "origin/main"],
        check=True,
    )

    merge_base = run(
        [
            "git",
            "merge-base",
            "HEAD",
            "origin/main",
        ],
        check=True,
    )

    local = run(
        ["git", "rev-parse", "HEAD"],
        check=True,
    )

    return {
        "local_head_after_fetch": (local.stdout or "").strip(),
        "github_main": (remote_head.stdout or "").strip(),
        "merge_base": (merge_base.stdout or "").strip(),
    }


def export_github_archive():
    print("\n=== GITHUB MAIN SNAPSHOT ===")

    archive = RECOVERY / "github_main.tar"

    with archive.open("wb") as f:
        p = subprocess.run(
            [
                "git",
                "archive",
                "--format=tar",
                "origin/main",
            ],
            cwd=str(ROOT),
            stdout=f,
            stderr=subprocess.PIPE,
        )

    if p.returncode != 0:
        print(p.stderr.decode("utf-8", "replace"))
        raise RuntimeError("git archive origin/main failed")

    with tarfile.open(archive, "r") as tar:
        tar.extractall(GITHUB_SNAPSHOT)

    print("[GITHUB ARCHIVE]", archive)
    print("[GITHUB SNAPSHOT]", GITHUB_SNAPSHOT)


def compare_names():
    print("\n=== FILE INVENTORY COMPARISON ===")

    local_files = set()

    for p in WORKTREE_BACKUP.rglob("*"):
        if p.is_file():
            local_files.add(
                str(p.relative_to(WORKTREE_BACKUP))
            )

    github_files = set()

    for p in GITHUB_SNAPSHOT.rglob("*"):
        if p.is_file():
            github_files.add(
                str(p.relative_to(GITHUB_SNAPSHOT))
            )

    only_local = sorted(local_files - github_files)
    only_github = sorted(github_files - local_files)
    both = sorted(local_files & github_files)

    report = []

    report.append("LOCAL FILES      = %d" % len(local_files))
    report.append("GITHUB FILES     = %d" % len(github_files))
    report.append("COMMON FILES     = %d" % len(both))
    report.append("LOCAL ONLY       = %d" % len(only_local))
    report.append("GITHUB ONLY      = %d" % len(only_github))

    report.append("\n--- LOCAL ONLY ---")
    report.extend(only_local)

    report.append("\n--- GITHUB ONLY ---")
    report.extend(only_github)

    text = "\n".join(report) + "\n"

    with REPORT.open("a", encoding="utf-8") as f:
        f.write("\n=== FILE INVENTORY ===\n")
        f.write(text)

    print(text)


def write_report(meta_before, meta_after):
    print("\n=== FINAL REPORT ===")

    payload = {
        "timestamp_utc": STAMP,
        "root": str(ROOT),
        "live_orders": 0,
        "execution_mode": os.environ.get("EXECUTION_MODE"),
        "execution": os.environ.get("EXECUTION"),
        "honeycomb_mode": os.environ.get("HONEYCOMB_MODE"),
        "live_armed": os.environ.get("LIVE_ARMED"),
        "before": meta_before,
        "after": meta_after,
        "recovery": str(RECOVERY),
        "working_tree_backup": str(WORKTREE_BACKUP),
        "github_snapshot": str(GITHUB_SNAPSHOT),
    }

    with REPORT.open("w", encoding="utf-8") as f:
        f.write("HONEYCOMB RECONCILIATION STAGE 1\n")
        f.write("=" * 70 + "\n")
        f.write(json.dumps(payload, indent=2, ensure_ascii=False))
        f.write("\n")

    print(json.dumps(payload, indent=2, ensure_ascii=False))


def main():
    print("=" * 70)
    print(" HONEYCOMB — NON-DESTRUCTIVE RECONCILIATION STAGE 1")
    print("=" * 70)
    print("ROOT:", ROOT)
    print("RECOVERY:", RECOVERY)
    print("LIVE ORDERS: 0")
    print()
    print("NO SOURCE FILE WILL BE MODIFIED.")
    print("NO FILE WILL BE DELETED.")
    print("NO .env WILL BE MODIFIED.")
    print("NO DATABASE WILL BE MODIFIED.")
    print()

    if not (ROOT / ".git").exists():
        raise SystemExit("FATAL: .git bulunamadı.")

    meta_before = git_metadata()

    print("\nLOCAL HEAD BEFORE:")
    print(meta_before["local_head"])

    copy_worktree()
    write_manifest()
    git_state()

    fetch_github()

    meta_after = github_metadata()

    print("\nLOCAL HEAD:")
    print(meta_after["local_head_after_fetch"])

    print("\nGITHUB MAIN:")
    print(meta_after["github_main"])

    print("\nCOMMON ANCESTOR:")
    print(meta_after["merge_base"])

    export_github_archive()
    compare_names()
    write_report(meta_before, meta_after)

    print("\n" + "=" * 70)
    print(" STAGE 1 TAMAMLANDI")
    print("=" * 70)
    print("LOCAL BACKUP :", WORKTREE_BACKUP)
    print("GITHUB COPY  :", GITHUB_SNAPSHOT)
    print("REPORT       :", REPORT)
    print("MANIFEST     :", MANIFEST)
    print("STATUS       :", STATUS)
    print("UNSTAGED DIFF:", DIFF_UNSTAGED)
    print("STAGED DIFF  :", DIFF_STAGED)
    print("UNTRACKED    :", UNTRACKED)
    print()
    print("HICBIR KAYNAK DOSYA DEGISTIRILMEDI.")
    print("HICBIR DOSYA SILINMEDI.")
    print("LIVE_ARMED =", os.environ.get("LIVE_ARMED"))
    print("=" * 70)


if __name__ == "__main__":
    main()
