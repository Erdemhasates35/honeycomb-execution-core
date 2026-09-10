#!/data/data/com.termux/files/usr/bin/python3
# -*- coding: utf-8 -*-

from pathlib import Path
import hashlib
import shutil
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path.cwd()
TARGET = ROOT / "alpha_core.py"

BACKUP_ROOT = (
    ROOT
    / ".honeycomb_tools"
    / "alpha_exact_backups"
    / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
)

BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
BACKUP = BACKUP_ROOT / "alpha_core.py"


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read():
    return TARGET.read_text(encoding="utf-8")


def write(text):
    TARGET.write_text(text, encoding="utf-8")


def backup():
    shutil.copy2(TARGET, BACKUP)
    print("[BACKUP]", sha256(TARGET))
    print("[BACKUP PATH]", BACKUP)


def rollback():
    shutil.copy2(BACKUP, TARGET)
    print("[ROLLBACK] alpha_core.py restored")


def remove_exact_block(text, start_marker, end_marker):
    start = text.find(start_marker)
    if start < 0:
        raise RuntimeError("START BLOCK NOT FOUND: " + repr(start_marker))

    end = text.find(end_marker, start)
    if end < 0:
        raise RuntimeError("END BLOCK NOT FOUND: " + repr(end_marker))

    return text[:start] + text[end:]


def patch():
    text = read()

    original = text

    # ------------------------------------------------------------
    # 1. Broken duplicate EMA prefix
    #
    # Existing corrupted form:
    #
    # def ema(arr: List[float], p: int) -> Optional[float]:
    #     if len(arr) < p:
    #         return hit[1] if hit else None
    #
    # def ema(arr, p):
    #
    # Keep the complete second implementation.
    # ------------------------------------------------------------

    block = """def ema(arr: List[float], p: int) -> Optional[float]:
    if len(arr) < p:
        return hit[1] if hit else None


"""

    if block in text:
        text = text.replace(block, "", 1)
        print("[ALPHA] removed broken EMA prefix")
    else:
        print("[ALPHA] broken EMA prefix already absent")

    # ------------------------------------------------------------
    # 2. Broken duplicate RSI prefix
    # ------------------------------------------------------------

    block = """def rsi(arr: List[float], p: int = 14) -> Optional[float]:
    if len(arr) < p + 1:
"""

    if block in text:
        text = text.replace(block, "", 1)
        print("[ALPHA] removed broken RSI prefix")
    else:
        print("[ALPHA] broken RSI prefix already absent")

    # ------------------------------------------------------------
    # 3. Broken duplicate ATR prefix
    # ------------------------------------------------------------

    block = """def atr(h: List[float], l: List[float], c: List[float], p: int = 14) -> Optional[float]:
    if len(c) < p + 1:
"""

    if block in text:
        text = text.replace(block, "", 1)
        print("[ALPHA] removed broken ATR prefix")
    else:
        print("[ALPHA] broken ATR prefix already absent")

    # ------------------------------------------------------------
    # 4. Eliminate literal /tmp references from the actual source.
    #
    # Do NOT alter behavior elsewhere. Only the known documentation
    # phrase is changed because runtime fallback is already repo-local.
    # ------------------------------------------------------------

    old_doc = '"""Create parent dir; fall back to /tmp if unwritable (fixes sqlite OperationalError)."""'
    new_doc = '"""Create parent dir; fall back to the repo-local runtime directory if unwritable."""'

    if old_doc in text:
        text = text.replace(old_doc, new_doc, 1)
        print("[ALPHA] removed /tmp documentation reference")

    if text == original:
        print("[ALPHA] NO CHANGES REQUIRED")

    write(text)


def compile_check():
    print("\n=== PY_COMPILE alpha_core.py ===")

    p = subprocess.run(
        [sys.executable, "-m", "py_compile", str(TARGET)],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
    )

    if p.returncode == 0:
        print("[PASS] alpha_core.py py_compile")
        return True

    print("[FAIL] alpha_core.py")
    if p.stdout:
        print(p.stdout)
    if p.stderr:
        print(p.stderr)

    return False


def ast_check():
    print("\n=== AST CHECK alpha_core.py ===")

    import ast

    try:
        tree = ast.parse(
            read(),
            filename=str(TARGET),
        )
    except Exception as e:
        print("[FAIL] AST:", repr(e))
        return False

    funcs = {}
    classes = {}

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs.setdefault(node.name, []).append(node.lineno)

        elif isinstance(node, ast.ClassDef):
            classes.setdefault(node.name, []).append(node.lineno)

    dup_funcs = {
        k: v for k, v in funcs.items()
        if len(v) > 1
    }

    dup_classes = {
        k: v for k, v in classes.items()
        if len(v) > 1
    }

    print(
        "[AST OK]",
        "top-level functions:",
        len(funcs),
        "top-level classes:",
        len(classes),
    )

    if dup_funcs:
        print("[INFO] duplicate top-level functions:", dup_funcs)

    if dup_classes:
        print("[FAIL] duplicate top-level classes:", dup_classes)
        return False

    return True


def forbidden_tmp_check():
    print("\n=== /tmp CHECK ===")

    bad = []

    for n, line in enumerate(read().splitlines(), 1):
        if "/tmp" in line:
            bad.append((n, line))

    if bad:
        for n, line in bad:
            print("[TMP FOUND]", n, line)
        return False

    print("[PASS] no /tmp reference")
    return True


def main():
    if not TARGET.exists():
        raise SystemExit("MISSING: alpha_core.py")

    print("============================================================")
    print(" HONEYCOMB — ALPHA EXACT STRUCTURAL REPAIR")
    print("============================================================")
    print("ROOT:", ROOT)
    print("TARGET:", TARGET)
    print("BACKUP:", BACKUP)
    print("LIVE ORDERS: 0")
    print()

    backup()

    old_hash = sha256(TARGET)

    try:
        patch()

        if not compile_check():
            raise RuntimeError("alpha_core.py compile failed")

        if not ast_check():
            raise RuntimeError("alpha_core.py AST failed")

        if not forbidden_tmp_check():
            raise RuntimeError("/tmp reference remains")

        new_hash = sha256(TARGET)

        print("\n=== HASH ===")
        print("OLD:", old_hash)
        print("NEW:", new_hash)
        print("CHANGED:", old_hash != new_hash)

        print("\n============================================================")
        print(" ALPHA STRUCTURAL REPAIR PASS")
        print("============================================================")
        print("py_compile : PASS")
        print("AST        : PASS")
        print("/tmp       : PASS")
        print("LIVE       : 0")
        print("BACKUP     :", BACKUP)

    except Exception as e:
        print("\n============================================================")
        print(" ALPHA REPAIR FAILED — ROLLBACK")
        print("============================================================")
        print(type(e).__name__ + ":", e)

        rollback()

        print("[VERIFY ROLLBACK]")
        compile_check()

        raise SystemExit(1)


if __name__ == "__main__":
    main()
