#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
import ast
import hashlib
import os
import re
import shutil
import subprocess
import time

ROOT = Path.cwd()

TARGETS = [
    ROOT / "alpha_core.py",
    ROOT / "live" / "kernel.py",
    ROOT / "live" / "kernel_hardened_sign.py",
    ROOT / "extreme_scanner_engine.py",
]

BACKUP_ROOT = ROOT / ".honeycomb_tools" / "final_structural_repair_v2_backups"
STAMP = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
BACKUP = BACKUP_ROOT / STAMP
BACKUP.mkdir(parents=True, exist_ok=True)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read(path):
    return path.read_text(encoding="utf-8", errors="ignore")


def write(path, text):
    path.write_text(text, encoding="utf-8")


def backup(path):
    dst = BACKUP / path.relative_to(ROOT)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, dst)
    print("[BACKUP]", path.relative_to(ROOT), sha256(path))


def restore_all():
    print("\n[ROLLBACK]")
    for path in TARGETS:
        src = BACKUP / path.relative_to(ROOT)
        if src.exists():
            shutil.copy2(src, path)
            print("[RESTORED]", path.relative_to(ROOT))


def top_level_block_span(lines, start):
    """
    start: line index of a top-level class/def.
    Returns [start, end), ending at next top-level class/def.
    """
    i = start + 1
    while i < len(lines):
        line = lines[i]
        if line.strip() and not line.startswith((" ", "\t")):
            if re.match(r"^(class|def|async\s+def)\s+", line):
                return start, i
        i += 1
    return start, len(lines)


def find_top_level_classes(text, name=None):
    lines = text.splitlines(keepends=True)
    out = []

    for i, line in enumerate(lines):
        if not line.startswith((" ", "\t")):
            m = re.match(r"^class\s+([A-Za-z_][A-Za-z0-9_]*)\b", line)
            if m and (name is None or m.group(1) == name):
                out.append((i, m.group(1)))

    return lines, out


def remove_first_duplicate_class(text, class_name):
    lines, matches = find_top_level_classes(text, class_name)

    if len(matches) < 2:
        return text, False

    start, _ = matches[0]
    end = top_level_block_span(lines, start)[1]

    print(
        "[REMOVE DUPLICATE CLASS]",
        class_name,
        "lines",
        start + 1,
        "-",
        end,
    )

    del lines[start:end]
    return "".join(lines), True


def remove_first_class_method_block(text, class_name, method_name):
    lines, classes = find_top_level_classes(text, class_name)

    if not classes:
        return text, False

    class_start = classes[0][0]
    class_end = top_level_block_span(lines, class_start)[1]

    methods = []

    for i in range(class_start + 1, class_end):
        line = lines[i]
        if re.match(
            rf"^    (?:async\s+)?def\s+{re.escape(method_name)}\s*\(",
            line,
        ):
            methods.append(i)

    if len(methods) < 2:
        return text, False

    start = methods[0]
    end = methods[1]

    print(
        "[REMOVE DUPLICATE METHOD BLOCK]",
        class_name + "." + method_name,
        "lines",
        start + 1,
        "-",
        end,
    )

    del lines[start:end]
    return "".join(lines), True


def patch_alpha():
    path = ROOT / "alpha_core.py"
    current = read(path)

    # alpha_core.py'nin mevcut canonical gövdesini koru.
    # Sadece bozuk prefix'i origin/main'deki canonical prefix ile değiştir.
    try:
        canonical = subprocess.check_output(
            ["git", "show", "origin/main:alpha_core.py"],
            cwd=ROOT,
            stderr=subprocess.STDOUT,
        ).decode("utf-8", errors="ignore")
    except Exception as e:
        raise RuntimeError(
            "origin/main alpha_core.py okunamadı; güvenli onarım durduruldu: "
            + str(e)
        )

    marker = "from __future__ import annotations"

    if marker not in canonical:
        raise RuntimeError("origin/main alpha_core.py canonical marker yok")

    if marker not in current:
        raise RuntimeError("mevcut alpha_core.py içinde future-import bulunamadı")

    canonical_prefix = canonical[: canonical.index(marker)]
    current_suffix = current[current.index(marker) :]

    repaired = canonical_prefix + current_suffix

    # Kullanıcının açık talebi: /tmp yok.
    repaired = repaired.replace(
        'os.path.expanduser("/tmp/.honeycomb")',
        'os.path.join(ROOT, ".honeycomb_runtime")',
    )

    repaired = repaired.replace(
        "os.path.expanduser('/tmp/.honeycomb')",
        'os.path.join(ROOT, ".honeycomb_runtime")',
    )

    repaired = repaired.replace(
        'os.path.expanduser("~/.honeycomb")',
        'os.path.join(ROOT, ".honeycomb_runtime")',
    )

    repaired = repaired.replace(
        "os.path.expanduser('~/.honeycomb')",
        'os.path.join(ROOT, ".honeycomb_runtime")',
    )

    # Bozuk escape kalıntısı varsa düzelt.
    repaired = repaired.replace(r"os.path.expanduser('\~/.honeycomb')",
                                "os.path.expanduser('~/.honeycomb')")

    write(path, repaired)

    print("[ALPHA] canonical prefix restored; existing module body preserved")


def patch_kernel():
    path = ROOT / "live" / "kernel.py"
    text = read(path)

    # Yanlış eklenen \~ escape'lerini düzelt.
    text = text.replace(r"\~/.honeycomb", "~/.honeycomb")
    text = text.replace(r"\~", "~")

    # İlk bozuk/duplicate CircuitBreaker.
    text, _ = remove_first_duplicate_class(text, "CircuitBreaker")

    # İlk bozuk CryptographicAuditLedger.
    text, _ = remove_first_duplicate_class(
        text,
        "CryptographicAuditLedger",
    )

    # İlk PartialProfitEngine duplicate.
    text, _ = remove_first_duplicate_class(
        text,
        "PartialProfitEngine",
    )

    # İlk DynamicTrailingStopEngine duplicate.
    text, _ = remove_first_duplicate_class(
        text,
        "DynamicTrailingStopEngine",
    )

    # CryptographicAuditLedger içinde iki ayrı method seti vardı.
    text, _ = remove_first_class_method_block(
        text,
        "CryptographicAuditLedger",
        "_last_hash",
    )

    write(path, text)

    print("[KERNEL] duplicate structural blocks repaired")


def patch_hardened_sign():
    path = ROOT / "live" / "kernel_hardened_sign.py"
    text = read(path)

    lines = text.splitlines(keepends=True)

    # Top-level hardened_http fonksiyonlarını bul.
    starts = []

    for i, line in enumerate(lines):
        if not line.startswith((" ", "\t")) and re.match(
            r"^def\s+hardened_http\s*\(",
            line,
        ):
            starts.append(i)

    if len(starts) >= 2:
        # İlk yarım duplicate fonksiyonu tamamen kaldır.
        s = starts[0]
        e = starts[1]

        print(
            "[HARDENED SIGN] remove first duplicate hardened_http:",
            s + 1,
            "-",
            e,
        )

        del lines[s:e]

    text = "".join(lines)

    # İkinci gövdedeki duplicate body/url/data/headers bloğu.
    lines = text.splitlines(keepends=True)

    # hardened_http içindeki son fonksiyon sınırını bul.
    fn_start = None
    fn_end = len(lines)

    for i, line in enumerate(lines):
        if not line.startswith((" ", "\t")) and re.match(
            r"^def\s+hardened_http\s*\(",
            line,
        ):
            fn_start = i
            break

    if fn_start is None:
        raise RuntimeError("hardened_http bulunamadı")

    for i in range(fn_start + 1, len(lines)):
        if lines[i].strip() and not lines[i].startswith((" ", "\t")):
            if re.match(r"^(class|def|async\s+def)\s+", lines[i]):
                fn_end = i
                break

    body_positions = []

    for i in range(fn_start, fn_end):
        if re.match(r"^\s*body\s*=\s*urllib\.parse\.urlencode\s*\(", lines[i]):
            body_positions.append(i)

    if len(body_positions) >= 2:
        second_body = body_positions[1]

        last_err = None
        for i in range(second_body, fn_end):
            if re.match(r"^\s*last_err\s*=\s*None\s*$", lines[i]):
                last_err = i
                break

        if last_err is None:
            raise RuntimeError(
                "hardened_http duplicate body bloğu bulundu fakat "
                "last_err sınırı bulunamadı"
            )

        print(
            "[HARDENED SIGN] remove duplicate request block:",
            second_body + 1,
            "-",
            last_err,
        )

        del lines[second_body:last_err]

    text = "".join(lines)

    # Yanlış escape'leri temizle.
    text = text.replace(r"\~/.honeycomb", "~/.honeycomb")
    text = text.replace(r"\~", "~")

    write(path, text)

    print("[HARDENED SIGN] repaired")


def patch_scanner():
    path = ROOT / "extreme_scanner_engine.py"
    text = read(path)

    lines = text.splitlines(keepends=True)

    # Duplicate "from live.kernel import (" bloklarını bul.
    imports = []

    for i, line in enumerate(lines):
        if line.startswith("from live.kernel import ("):
            imports.append(i)

    if len(imports) >= 2:
        second_import = imports[1]

        # Canonical ACCOUNT_LABEL satırını bul.
        canonical_account = None

        for i in range(second_import, len(lines)):
            if (
                'ACCOUNT_LABEL = os.getenv("ACCOUNT_LABEL", "SCANNER-OMEGA")'
                in lines[i]
            ):
                canonical_account = i
                break

        if canonical_account is None:
            raise RuntimeError(
                "SCANNER-OMEGA canonical ACCOUNT_LABEL bulunamadı"
            )

        print(
            "[SCANNER] remove duplicate config/import block:",
            second_import + 1,
            "-",
            canonical_account,
        )

        # Canonical ACCOUNT_LABEL satırını koru.
        del lines[second_import:canonical_account]

    text = "".join(lines)

    # Yanlış escape varsa düzelt.
    text = text.replace(r"\~/.honeycomb", "~/.honeycomb")
    text = text.replace(r"\~", "~")

    write(path, text)

    print("[SCANNER] repaired")


def syntax_check():
    print("\n=== PY_COMPILE ===")

    for path in TARGETS:
        r = subprocess.run(
            ["python3", "-m", "py_compile", str(path)],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )

        if r.returncode != 0:
            print("[FAIL]", path.relative_to(ROOT))
            print(r.stdout)
            print(r.stderr)
            return False

        print("[OK]", path.relative_to(ROOT))

    return True


def ast_check():
    print("\n=== AST ===")

    for path in TARGETS:
        try:
            tree = ast.parse(
                read(path),
                filename=str(path),
            )
        except SyntaxError as e:
            print("[AST FAIL]", path.relative_to(ROOT), e)
            return False

        classes = {}

        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                classes.setdefault(node.name, []).append(node.lineno)

        duplicates = {
            k: v
            for k, v in classes.items()
            if len(v) > 1
        }

        if duplicates:
            print(
                "[DUPLICATE CLASS FAIL]",
                path.relative_to(ROOT),
                duplicates,
            )
            return False

        print(
            "[AST OK]",
            path.relative_to(ROOT),
            "top-level classes unique",
        )

    return True


def conflict_check():
    print("\n=== CONFLICT MARKERS ===")

    bad = []

    for path in TARGETS:
        for n, line in enumerate(
            read(path).splitlines(),
            start=1,
        ):
            if re.match(
                r"^\s*(<<<<<<<|=======|>>>>>>>)\s*$",
                line,
            ):
                bad.append(
                    f"{path.relative_to(ROOT)}:{n}:{line}"
                )

    if bad:
        for x in bad:
            print("[CONFLICT]", x)
        return False

    print("[OK] repaired core files contain no Git conflict markers")
    return True


def tmp_check():
    print("\n=== /tmp CHECK ===")

    bad = []

    for path in TARGETS:
        for n, line in enumerate(
            read(path).splitlines(),
            start=1,
        ):
            if "/tmp/" in line or "/tmp" in line:
                bad.append(
                    f"{path.relative_to(ROOT)}:{n}:{line}"
                )

    if bad:
        for x in bad:
            print("[TMP FOUND]", x)
        return False

    print("[OK] no /tmp references in repaired core")
    return True


def duplicate_name_report():
    print("\n=== STRUCTURAL REPORT ===")

    for path in TARGETS:
        text = read(path)
        lines, classes = find_top_level_classes(text)

        names = {}
        for _, name in classes:
            names.setdefault(name, 0)
            names[name] += 1

        dup = {k: v for k, v in names.items() if v > 1}

        print(
            path.relative_to(ROOT),
            "duplicate_top_level_classes=",
            dup if dup else "NONE",
        )


def main():
    print("============================================================")
    print(" HONEYCOMB — FINAL STRUCTURAL REPAIR V2")
    print("============================================================")
    print("ROOT:", ROOT)
    print("BACKUP:", BACKUP)
    print("TEMP DIRECTORY: NONE")
    print()

    for path in TARGETS:
        if not path.exists():
            raise SystemExit(f"MISSING TARGET: {path}")
        backup(path)

    original_hashes = {
        p: sha256(p)
        for p in TARGETS
    }

    try:
        patch_alpha()
        patch_kernel()
        patch_hardened_sign()
        patch_scanner()

        if not syntax_check():
            raise RuntimeError("py_compile başarısız")

        if not ast_check():
            raise RuntimeError("AST doğrulaması başarısız")

        if not conflict_check():
            raise RuntimeError("conflict marker bulundu")

        if not tmp_check():
            raise RuntimeError("/tmp referansı bulundu")

        duplicate_name_report()

        print("\n=== HASH DELTA ===")

        for path in TARGETS:
            old = original_hashes[path]
            new = sha256(path)
            print(
                path.relative_to(ROOT),
                "OLD=", old,
                "NEW=", new,
                "CHANGED=", old != new,
            )

        print("\n============================================================")
        print(" STRUCTURAL REPAIR SUCCESS")
        print("============================================================")
        print("4/4 py_compile : PASS")
        print("4/4 AST         : PASS")
        print("duplicates      : CHECKED")
        print("conflict markers: CHECKED")
        print("/tmp            : CHECKED")
        print("LIVE ORDERS     : NOT EXECUTED")
        print("BACKUP          :", BACKUP)

    except Exception as e:
        print("\n============================================================")
        print(" REPAIR FAILED — AUTOMATIC ROLLBACK")
        print("============================================================")
        print(type(e).__name__ + ":", e)

        restore_all()

        print("\nROLLBACK COMPLETE")
        print("Original files restored from:", BACKUP)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
