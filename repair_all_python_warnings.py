#!/usr/bin/env python3
from pathlib import Path
import os
import re
import ast
import py_compile
import warnings

ROOT = Path(__file__).resolve().parent

EXCLUDED = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
}

def excluded(p: Path) -> bool:
    parts = set(p.parts)
    if parts & EXCLUDED:
        return True
    return any(
        x.startswith(".honeycomb_recovery_DISABLED")
        or x.startswith(".honeycomb_tools_DISABLED")
        or x.startswith("backups")
        or "backup" in x.lower()
        for x in p.parts
    )

def python_files():
    return [
        p for p in ROOT.rglob("*.py")
        if not excluded(p)
    ]

def repair_text(text: str) -> str:
    replacements = {
        r"~": "~",
        r"(": "(",
        r")": ")",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    return text

changed = []

for path in python_files():
    try:
        original = path.read_text(
            encoding="utf-8",
            errors="replace",
        )
        repaired = repair_text(original)

        if repaired != original:
            path.write_text(
                repaired,
                encoding="utf-8",
            )
            changed.append(str(path.relative_to(ROOT)))
    except Exception as exc:
        print("READ/WRITE FAIL:", path, repr(exc))

print("REPAIRED:", len(changed))

for p in changed:
    print("FIX:", p)

print("\n=== PYTHON COMPILE ===")

failures = []

for path in python_files():
    try:
        py_compile.compile(
            str(path),
            doraise=True,
        )
    except Exception as exc:
        failures.append(
            (
                str(path.relative_to(ROOT)),
                repr(exc),
            )
        )

if failures:
    print("COMPILE FAILURES:", len(failures))
    for path, error in failures:
        print(path)
        print(error)
else:
    print("COMPILE FAILURES: 0")

print("\n=== AST ===")

ast_failures = []

for path in python_files():
    try:
        ast.parse(
            path.read_text(
                encoding="utf-8",
                errors="replace",
            ),
            filename=str(path),
        )
    except Exception as exc:
        ast_failures.append(
            (
                str(path.relative_to(ROOT)),
                repr(exc),
            )
        )

if ast_failures:
    print("AST FAILURES:", len(ast_failures))
    for path, error in ast_failures:
        print(path)
        print(error)
else:
    print("AST FAILURES: 0")

print("\n=== WARNING SCAN ===")

warning_files = []

for path in python_files():
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            source = path.read_text(
                encoding="utf-8",
                errors="replace",
            )
            compile(
                source,
                str(path),
                "exec",
            )

            relevant = [
                str(w.message)
                for w in caught
                if "invalid escape sequence" in str(w.message)
            ]

            if relevant:
                warning_files.append(
                    (
                        str(path.relative_to(ROOT)),
                        relevant,
                    )
                )
    except Exception:
        pass

if warning_files:
    print("INVALID ESCAPE FILES:", len(warning_files))
    for path, warnings_found in warning_files:
        print(path)
        for warning in warnings_found:
            print(" ", warning)
else:
    print("INVALID ESCAPE WARNINGS: 0")

print("\nDONE")
