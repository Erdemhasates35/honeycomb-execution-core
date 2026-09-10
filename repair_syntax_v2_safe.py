#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
HONEYCOMB SAFE SYNTAX REPAIR V2

Amaç:
- Python syntax/conflict kaynaklı bozulmaları güvenli şekilde düzeltmek.
- Kod bloklarını sessizce silmemek.
- Conflict taraflarını ayrı ayrı korumak.
- .env ve runtime/veritabanlarına dokunmamak.
- Live execution başlatmamak.

ÖNEMLİ:
Bu script semantik refactor yapmaz.
API/emir/risk fonksiyonlarını değiştirmez.
"""

from __future__ import annotations

import ast
import datetime as dt
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent

STAMP = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
BACKUP = ROOT / "backups" / f"syntax_v2_{STAMP}"

EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "__pycache__",
    "backups",
    "runtime",
    "logs",
    ".honeycomb_runtime",
}

EXCLUDED_FILE_NAMES = {
    ".env",
}

EXCLUDED_FILE_PREFIXES = (
    ".env.",
)

CONFLICT_BEGIN = "<<<<<<<"
CONFLICT_MIDDLE = "======="
CONFLICT_END = ">>>>>>>"

TARGET_FILES = [
    ROOT / "alpha_core.py",
    ROOT / "extreme_scanner_omega.py",
    ROOT / "extreme_scanner_engine.py",
    ROOT / "live" / "__init__.py",
    ROOT / "live" / "kernel.py",
    ROOT / "live" / "kernel_hardened_sign.py",
]


def is_excluded(path: Path) -> bool:
    try:
        rel = path.relative_to(ROOT)
    except ValueError:
        return True

    for part in rel.parts:
        if part in EXCLUDED_DIRS:
            return True

    name = path.name

    if name in EXCLUDED_FILE_NAMES:
        return True

    if any(name.startswith(prefix) for prefix in EXCLUDED_FILE_PREFIXES):
        return True

    return False


def read_text(path: Path) -> str:
    return path.read_text(
        encoding="utf-8",
        errors="surrogateescape",
    )


def write_text(path: Path, text: str) -> None:
    path.write_text(
        text,
        encoding="utf-8",
        errors="surrogateescape",
        newline="\n",
    )


def backup_file(path: Path) -> None:
    rel = path.relative_to(ROOT)
    dst = BACKUP / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, dst)


def syntax_error(path: Path):
    try:
        ast.parse(read_text(path), filename=str(path))
        return None
    except SyntaxError as exc:
        return exc
    except Exception as exc:
        return exc


def compile_text(text: str, filename: str = "<candidate>"):
    try:
        ast.parse(text, filename=filename)
        return None
    except Exception as exc:
        return exc


def normalize_basic_characters(text: str) -> str:
    """
    Sadece güvenli görünmez karakterleri düzeltir.
    Unicode matematiksel/sembolik karakterleri körlemesine değiştirmez.
    """

    replacements = {
        "\ufeff": "",
        "\u00a0": " ",
        "\u200b": "",
        "\u200c": "",
        "\u200d": "",
        "\u2060": "",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    text = text.replace("\r\n", "\n")
    text = text.replace("\r", "\n")

    return text


def repair_filename_description_lines(text: str):
    """
    Örneğin:

        alpha_core.py — Honeycomb technical decision core.

    gibi Python olmayan açıklama satırlarını yorum yapar.

    Sadece açıkça filename + em dash/en dash formatındaki standalone
    satırlara uygulanır. String/docstring içeriğine dokunmaz.
    """

    lines = text.splitlines(True)
    changed = False

    pattern = re.compile(
        r"^(\s*)([A-Za-z0-9_.-]+\.py)\s+[—–-]\s+(.+?)\s*$"
    )

    out = []

    for line in lines:
        raw = line.rstrip("\r\n")
        newline = line[len(raw):]

        m = pattern.match(raw)

        if m:
            indent, filename, description = m.groups()

            # Zaten yorum ise dokunma.
            if not raw.lstrip().startswith("#"):
                out.append(
                    f"{indent}# {filename} — {description}{newline}"
                )
                changed = True
                continue

        out.append(line)

    return "".join(out), changed


def parse_conflict_blocks(lines):
    """
    Git conflict bloklarını tespit eder.

    Her blok:
        start
        ours
        separator
        theirs
        end

    şeklinde tutulur.

    Hiçbir satır burada silinmez.
    """

    blocks = []

    i = 0
    n = len(lines)

    while i < n:
        if not lines[i].lstrip().startswith(CONFLICT_BEGIN):
            i += 1
            continue

        start = i
        ours_start = i + 1

        j = ours_start
        while j < n and not lines[j].lstrip().startswith(CONFLICT_MIDDLE):
            j += 1

        if j >= n:
            i += 1
            continue

        separator = j
        theirs_start = j + 1

        k = theirs_start
        while k < n and not lines[k].lstrip().startswith(CONFLICT_END):
            k += 1

        if k >= n:
            i += 1
            continue

        end = k

        blocks.append(
            {
                "start": start,
                "ours_start": ours_start,
                "separator": separator,
                "theirs_start": theirs_start,
                "end": end,
                "ours": lines[ours_start:separator],
                "theirs": lines[theirs_start:end],
                "header": lines[start],
                "footer": lines[end],
            }
        )

        i = end + 1

    return blocks


def build_candidate_without_conflicts(lines, selected_side):
    """
    Conflict bloklarını seçilen tarafla değiştirerek candidate üretir.

    selected_side:
        ours
        theirs

    Conflict dışındaki bütün satırlar aynen korunur.
    """

    blocks = parse_conflict_blocks(lines)

    if not blocks:
        return "".join(lines)

    output = []

    cursor = 0

    for block in blocks:
        output.extend(lines[cursor:block["start"]])

        if selected_side == "ours":
            output.extend(block["ours"])
        else:
            output.extend(block["theirs"])

        cursor = block["end"] + 1

    output.extend(lines[cursor:])

    return "".join(output)


def candidate_score(exc):
    """
    Candidate seçiminde sadece syntax değerlendirmesi kullanılır.
    """

    if exc is None:
        return 100000

    if isinstance(exc, SyntaxError):
        msg = str(exc).lower()

        score = 0

        if "indentationerror" in type(exc).__name__.lower():
            score -= 100

        if "unexpected indent" in msg:
            score -= 100

        if "expected an indented block" in msg:
            score -= 100

        if "invalid syntax" in msg:
            score -= 10

        return score

    return -1000


def preserve_conflict_sides(path: Path, original_text: str, blocks) -> Path | None:
    if not blocks:
        return None

    rel = path.relative_to(ROOT)

    preserved = BACKUP / "preserved_conflicts" / rel
    preserved = preserved.with_suffix(
        preserved.suffix + ".conflict_preserved"
    )

    preserved.parent.mkdir(parents=True, exist_ok=True)

    output = []

    for number, block in enumerate(blocks, 1):
        output.append(
            f"\n"
            f"# ============================================================\n"
            f"# PRESERVED CONFLICT BLOCK {number}\n"
            f"# SOURCE: {rel}\n"
            f"# ============================================================\n"
        )

        output.append(
            "".join(block["header"])
        )

        output.append(
            "".join(block["ours"])
        )

        output.append(
            "".join(block["footer"])
        )

        output.append(
            "\n# ------------------------------------------------------------\n"
            "# SECOND CONFLICT SIDE\n"
            "# ------------------------------------------------------------\n"
        )

        output.append(
            "".join(block["theirs"])
        )

        output.append("\n")

    write_text(preserved, "".join(output))

    return preserved


def repair_conflicts(path: Path):
    text = read_text(path)
    lines = text.splitlines(True)

    blocks = parse_conflict_blocks(lines)

    if not blocks:
        return text, False, "no-conflict", None

    # Önce OURS candidate.
    ours = build_candidate_without_conflicts(lines, "ours")
    ours_exc = compile_text(ours, str(path))

    # Sonra THEIRS candidate.
    theirs = build_candidate_without_conflicts(lines, "theirs")
    theirs_exc = compile_text(theirs, str(path))

    # İkisi de compile oluyorsa mevcut repository HEAD tarafı olan OURS
    # seçilir. THEIRS eksiksiz backup'ta korunur.
    if ours_exc is None:
        chosen = ours
        selected = "OURS"
    elif theirs_exc is None:
        chosen = theirs
        selected = "THEIRS"
    else:
        # Hiçbiri tek başına compile olmuyorsa conflict markerlarını
        # aktif kaynakta bırakmak yerine mevcut dosyanın kaybolmaması için
        # dokunmadan başarısız döndür.
        preserved = preserve_conflict_sides(path, text, blocks)

        return (
            text,
            False,
            "conflict-unresolved",
            preserved,
        )

    preserved = preserve_conflict_sides(path, text, blocks)

    return (
        chosen,
        True,
        f"conflict-resolved-{selected}",
        preserved,
    )


def collect_python_files():
    files = []

    for root, dirs, filenames in os.walk(ROOT):
        root_path = Path(root)

        # excluded dirs prune
        dirs[:] = [
            d
            for d in dirs
            if d not in EXCLUDED_DIRS
        ]

        for name in filenames:
            if not name.endswith(".py"):
                continue

            path = root_path / name

            if is_excluded(path):
                continue

            # repair script itself hariç
            if path.name in {
                "repair_all_syntax_safe.py",
                "repair_syntax_v2_safe.py",
            }:
                continue

            files.append(path)

    return sorted(files)


def scan_syntax(paths):
    errors = []

    for path in paths:
        exc = syntax_error(path)

        if exc is not None:
            errors.append((path, exc))

    return errors


def scan_conflicts(paths):
    result = []

    for path in paths:
        try:
            text = read_text(path)
        except Exception:
            continue

        if (
            CONFLICT_BEGIN in text
            or CONFLICT_MIDDLE in text
            or CONFLICT_END in text
        ):
            result.append(path)

    return result


def print_error_list(title, errors):
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)

    if not errors:
        print("NONE")
        return

    for path, exc in errors:
        print()
        print(f"FILE: {path}")
        print(
            f"{type(exc).__name__}: "
            f"{exc}"
        )


def main():
    print("=" * 72)
    print("HONEYCOMB SAFE SYNTAX REPAIR V2")
    print("=" * 72)

    print(f"ROOT   = {ROOT}")

    BACKUP.mkdir(
        parents=True,
        exist_ok=True,
    )

    paths = collect_python_files()

    print(f"PYTHON_FILES = {len(paths)}")

    before = scan_syntax(paths)

    print_error_list(
        "INITIAL SYNTAX ERRORS",
        before,
    )

    changed = []
    failures = []
    preserved = []

    if not before:
        print()
        print("NO INITIAL SYNTAX ERRORS")
    else:
        print()
        print("=" * 72)
        print("SAFE PATCHING")
        print("=" * 72)

    for path in paths:
        exc = syntax_error(path)

        if exc is None:
            continue

        try:
            backup_file(path)

            original = read_text(path)
            working = normalize_basic_characters(original)

            description_fixed = False

            working, description_fixed = (
                repair_filename_description_lines(working)
            )

            # Conflict çözümünü yalnızca conflict içeren dosyada uygula.
            conflict_blocks = parse_conflict_blocks(
                working.splitlines(True)
            )

            if conflict_blocks:
                temp_path = path

                # Geçici normalize edilmiş içerik üzerinden conflict
                # çözümü yapıyoruz.
                old = read_text(temp_path)
                write_text(temp_path, working)

                try:
                    repaired, did_change, reason, saved = (
                        repair_conflicts(temp_path)
                    )
                finally:
                    # repaired kullanılacaksa tekrar yazacağız.
                    pass

                if saved is not None:
                    preserved.append(saved)

                if reason == "conflict-unresolved":
                    # Orijinal çalışan dosyayı kaybetme.
                    write_text(temp_path, old)
                    failures.append(
                        (
                            str(path),
                            reason,
                        )
                    )
                    continue

                working = repaired
                did_change = True

            else:
                did_change = (
                    working != original
                    or description_fixed
                )

            if working != original:
                write_text(path, working)

            # Son doğrulama.
            final_exc = syntax_error(path)

            if final_exc is not None:
                # Otomatik rollback YOK.
                # Çünkü kullanıcı kodunun üzerine sessizce yazılmıyor;
                # mevcut değişiklik BACKUP altında bulunuyor.
                failures.append(
                    (
                        str(path),
                        f"still-invalid: {final_exc}",
                    )
                )

            elif did_change:
                changed.append(
                    (
                        str(path),
                        "syntax/character/conflict-safe-repair",
                    )
                )

        except Exception as exc:
            failures.append(
                (
                    str(path),
                    repr(exc),
                )
            )

    after = scan_syntax(paths)
    conflicts = scan_conflicts(paths)

    print_error_list(
        "FINAL SYNTAX ERRORS",
        after,
    )

    print()
    print("=" * 72)
    print("FINAL CONFLICT SCAN")
    print("=" * 72)

    print(f"REMAINING_CONFLICT_FILES = {len(conflicts)}")

    for path in conflicts:
        print(f"CONFLICT: {path}")

    print()
    print("=" * 72)
    print("RESULT")
    print("=" * 72)

    print(f"BACKUP                = {BACKUP}")
    print(f"PYTHON_FILES          = {len(paths)}")
    print(f"INITIAL_SYNTAX_ERRORS = {len(before)}")
    print(f"FINAL_SYNTAX_ERRORS   = {len(after)}")
    print(f"CONFLICT_FILES        = {len(conflicts)}")
    print(f"CHANGED_FILES         = {len(changed)}")
    print(f"REPAIR_FAILURES       = {len(failures)}")
    print(f"PRESERVED_CONFLICTS   = {len(preserved)}")

    if changed:
        print()
        print("CHANGED_FILES")
        for path, reason in changed:
            print(f"{path} | {reason}")

    if failures:
        print()
        print("REPAIR_FAILURES")
        for item in failures:
            print(item)

    if preserved:
        print()
        print("PRESERVED_CONFLICT_ARTIFACTS")
        for path in preserved:
            print(path)

    print()
    print("ENV_MODIFIED          = NO")
    print("DATABASE_MODIFIED     = NO")
    print("RUNTIME_MODIFIED      = NO")
    print("LIVE_ENGINE_STARTED   = NO")
    print("LIVE_ORDER_CALLED     = NO")
    print("GIT_COMMIT             = NO")
    print("GIT_PUSH               = NO")

    print()
    if not after:
        print("PYTHON_SYNTAX = PASS")
    else:
        print("PYTHON_SYNTAX = REMAINING_ERRORS")

    if conflicts:
        print("CONFLICT_STATUS = REMAINING_CONFLICTS")
    else:
        print("CONFLICT_STATUS = CLEAN")

    print()
    print("NOT: Semantic/runtime/API/risk validation has NOT been claimed.")


if __name__ == "__main__":
    main()
