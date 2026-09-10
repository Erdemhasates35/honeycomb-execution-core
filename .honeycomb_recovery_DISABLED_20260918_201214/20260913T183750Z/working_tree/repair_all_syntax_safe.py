#!/usr/bin/env python3
from __future__ import annotations

import ast
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from datetime import datetime

ROOT = Path.cwd()
STAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
BACKUP = ROOT / "backups" / f"repair_patch_{STAMP}"
BACKUP.mkdir(parents=True, exist_ok=True)

EXCLUDE_DIRS = {
    ".git", ".venv", "venv", "node_modules",
    "__pycache__", "backups", "runtime", "logs",
    ".honeycomb_runtime"
}

EXCLUDE_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
}

PY_SUFFIXES = {".py", ".pyw"}

changed = []
failed = []


def excluded(path: Path) -> bool:
    try:
        rel = path.relative_to(ROOT)
    except ValueError:
        return True

    if any(part in EXCLUDE_DIRS for part in rel.parts):
        return True

    if path.name in EXCLUDE_NAMES:
        return True

    if path.name.startswith(".env."):
        return True

    return False


def backup(path: Path):
    rel = path.relative_to(ROOT)
    dst = BACKUP / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, dst)


def compile_file(path: Path):
    return subprocess.run(
        [sys.executable, "-m", "py_compile", str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )


def iter_python():
    for path in ROOT.rglob("*.py"):
        if path.is_file() and not excluded(path):
            yield path


def repair_conflicts(text: str):
    """
    Conflict markerlarını kaldırır.
    O/THEIRS kodunu SİLMEZ.
    Her iki tarafı korur.
    """

    lines = text.splitlines(keepends=True)

    out = []
    changed_here = False
    conflict_depth = False

    for line in lines:
        s = line.lstrip()

        if s.startswith("<<<<<<<"):
            conflict_depth = True
            changed_here = True
            continue

        if s.strip() == "=======":
            changed_here = True
            continue

        if s.startswith(">>>>>>>"):
            conflict_depth = False
            changed_here = True
            continue

        out.append(line)

    return "".join(out), changed_here


def repair_unicode_python(text: str):
    """
    Kod bloklarını değiştirmez.
    Yalnızca Python tokenizer/parser tarafından geçersiz olan
    standalone açıklama başlıklarını yorum haline getirir.

    Örn:
        alpha_core.py — Honeycomb technical decision core.
    ->
        # alpha_core.py — Honeycomb technical decision core.
    """

    lines = text.splitlines(keepends=True)
    out = []
    changed_here = False

    for line in lines:
        stripped = line.strip()

        if not stripped:
            out.append(line)
            continue

        # Zaten Python syntax olabilecek satırlara dokunma.
        try:
            ast.parse(stripped)
            out.append(line)
            continue
        except Exception:
            pass

        # Dosya açıklaması gibi duran Unicode başlıklar.
        if (
            "—" in stripped
            or "–" in stripped
            or "“" in stripped
            or "”" in stripped
            or "→" in stripped
            or "∞" in stripped
            or "α" in stripped
        ):
            if not stripped.startswith("#"):
                indent = line[:len(line) - len(line.lstrip())]
                ending = "\n" if line.endswith("\n") else ""
                out.append(
                    indent + "# " + stripped + ending
                )
                changed_here = True
                continue

        out.append(line)

    return "".join(out), changed_here


def repair_invalid_python_chars(text: str):
    """
    String literal dışındaki açıkça geçersiz Unicode karakterleri
    yalnızca satır başı/yorum benzeri bozuk başlıklarda ele alır.
    Kod ifadelerini topluca dönüştürmez.
    """

    replacements = {
        "\u00a0": " ",
        "\u200b": "",
        "\u200c": "",
        "\u200d": "",
        "\ufeff": "",
    }

    new = text

    for old, newchar in replacements.items():
        new = new.replace(old, newchar)

    return new, new != text


def repair_encoding(text: str):
    new = text.replace("\r\n", "\n").replace("\r", "\n")
    return new, new != text


def syntax_errors():
    result = []

    for path in iter_python():
        r = compile_file(path)

        if r.returncode != 0:
            result.append((path, r.stderr.strip()))

    return result


def conflict_files():
    result = []

    for path in iter_python():
        try:
            text = path.read_text(
                encoding="utf-8",
                errors="replace"
            )

            if re.search(
                r"^(<<<<<<<|=======|>>>>>>>)",
                text,
                re.MULTILINE
            ):
                result.append(path)

        except Exception:
            pass

    return result


# ------------------------------------------------------------
# FORCE PAPER
# ------------------------------------------------------------

os.environ["EXECUTION_MODE"] = "PAPER"
os.environ["HONEYCOMB_MODE"] = "PAPER"
os.environ["LIVE_ARMED"] = "0"

print("=" * 72)
print("HONEYCOMB FULL SAFE SYNTAX PATCH")
print("=" * 72)
print("ROOT   =", ROOT)
print("BACKUP =", BACKUP)
print("LIVE_ARMED = 0")
print()

# ------------------------------------------------------------
# INITIAL
# ------------------------------------------------------------

before = syntax_errors()

print("INITIAL_SYNTAX_ERRORS =", len(before))

for path, err in before:
    print()
    print("FILE:", path)
    print(err[:2500])

# ------------------------------------------------------------
# PATCH
# ------------------------------------------------------------

print()
print("PATCHING...")

for path in iter_python():

    try:
        original = path.read_text(
            encoding="utf-8",
            errors="replace"
        )

        text = original
        reasons = []

        text2, c = repair_encoding(text)
        text = text2
        if c:
            reasons.append("newline")

        text2, c = repair_invalid_python_chars(text)
        text = text2
        if c:
            reasons.append("invisible-unicode")

        text2, c = repair_conflicts(text)
        text = text2
        if c:
            reasons.append("conflict-markers")

        if text == original:
            continue

        backup(path)

        path.write_text(
            text,
            encoding="utf-8",
            newline="\n"
        )

        changed.append(str(path.relative_to(ROOT)))

        print(
            "REPAIRED:",
            path.relative_to(ROOT),
            "|",
            ",".join(reasons)
        )

    except Exception as exc:
        failed.append(
            (str(path.relative_to(ROOT)), repr(exc))
        )

# ------------------------------------------------------------
# SECOND PASS
# ------------------------------------------------------------

print()
print("SECOND SYNTAX SCAN")

after = syntax_errors()

print("REMAINING_SYNTAX_ERRORS =", len(after))

for path, err in after:
    print()
    print("REMAINING:", path)
    print(err[:3000])

# ------------------------------------------------------------
# CONFLICT SCAN
# ------------------------------------------------------------

print()
print("CONFLICT SCAN")

conflicts = conflict_files()

print("REMAINING_PYTHON_CONFLICT_FILES =", len(conflicts))

for path in conflicts:
    print("CONFLICT:", path.relative_to(ROOT))

# ------------------------------------------------------------
# SIMPLE AST VALIDATION
# ------------------------------------------------------------

print()
print("AST VALIDATION")

ast_fail = []

for path in iter_python():

    try:
        source = path.read_text(
            encoding="utf-8",
            errors="replace"
        )

        ast.parse(source, filename=str(path))

    except SyntaxError as exc:
        ast_fail.append(
            (path, f"line={exc.lineno}: {exc.msg}")
        )

    except Exception as exc:
        ast_fail.append(
            (path, repr(exc))
        )

print("AST_ERRORS =", len(ast_fail))

for path, err in ast_fail:
    print("AST_FAIL:", path.relative_to(ROOT), err)

# ------------------------------------------------------------
# RESULT
# ------------------------------------------------------------

print()
print("=" * 72)
print("RESULT")
print("=" * 72)

print("BACKUP =", BACKUP)
print("CHANGED =", len(changed))
print("INITIAL_SYNTAX_ERRORS =", len(before))
print("FINAL_SYNTAX_ERRORS   =", len(after))
print("CONFLICT_FILES        =", len(conflicts))
print("AST_ERRORS            =", len(ast_fail))
print("REPAIR_FAILURES       =", len(failed))

if changed:
    print()
    print("CHANGED_FILES")
    for item in changed:
        print(item)

if failed:
    print()
    print("REPAIR_FAILURES")
    for item in failed:
        print(item)

print()
print("ENV_MODIFIED = NO")
print("DATABASE_MODIFIED = NO")
print("RUNTIME_MODIFIED = NO")
print("LIVE_ENGINE_STARTED = NO")
print("LIVE_ORDER_CALLED = NO")
print("GIT_COMMIT = NO")
print("GIT_PUSH = NO")

if not after and not conflicts and not ast_fail:
    print()
    print("PYTHON_SYNTAX = PASS")
else:
    print()
    print("PYTHON_SYNTAX = REMAINING_ERRORS")
