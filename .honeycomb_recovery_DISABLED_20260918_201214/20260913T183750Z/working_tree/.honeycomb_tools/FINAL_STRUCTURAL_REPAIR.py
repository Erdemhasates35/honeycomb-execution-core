#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
HONEYCOMB FINAL STRUCTURAL REPAIR

Amaç:
- Merge sonucu oluşmuş duplicate/orphan Python bloklarını hedefli düzeltmek.
- /tmp KULLANMAZ.
- .env / DB / log / runtime verisini değiştirmez.
- Canlı motoru çalıştırmaz.
- Her dosyayı SHA256 ile repo-local yedekler.
- Herhangi bir doğrulama başarısız olursa TÜM değişiklikleri geri alır.

Düzeltilecek dosyalar:
    alpha_core.py
    live/kernel.py
    live/kernel_hardened_sign.py
    extreme_scanner_engine.py
"""

from __future__ import annotations

import ast
import hashlib
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
BACKUP_ROOT = ROOT / ".honeycomb_tools" / "final_structural_repair_backups"

TARGETS = [
    ROOT / "alpha_core.py",
    ROOT / "live" / "kernel.py",
    ROOT / "live" / "kernel_hardened_sign.py",
    ROOT / "extreme_scanner_engine.py",
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def fail(msg: str):
    print("\n[ABORT]")
    print(msg)
    raise SystemExit(1)


def backup_all():
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    backup_dir = BACKUP_ROOT / stamp
    backup_dir.mkdir(parents=True, exist_ok=False)

    records = []

    for path in TARGETS:
        if not path.exists():
            fail("Eksik hedef dosya: %s" % path)

        rel = path.relative_to(ROOT)
        dst = backup_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dst)

        digest = sha256(path)
        records.append((path, dst, digest))
        print("[BACKUP] %-38s SHA256=%s" % (str(rel), digest))

    return backup_dir, records


def restore(records):
    print("\n[ROLLBACK] Doğrulama başarısız — orijinal dosyalar geri yükleniyor.")
    for src, backup, _digest in records:
        shutil.copy2(backup, src)
        print("[RESTORED] %s" % src.relative_to(ROOT))


def write(path: Path, text: str):
    path.write_text(text, encoding="utf-8")


def remove_prefix_before_marker(text: str, marker: str, label: str) -> str:
    pos = text.find(marker)

    if pos < 0:
        fail("%s: kanonik başlangıç marker'ı bulunamadı: %r" % (label, marker))

    if pos == 0:
        print("[OK] %s: prefix yok." % label)
        return text

    print("[FIX] %s: %d byte eski prefix kaldırılıyor." % (label, pos))
    return text[pos:]


def remove_first_duplicate_top_level_class(
    text: str,
    class_name: str,
) -> str:
    pattern = re.compile(
        r"(?m)^class\s+" + re.escape(class_name) + r"\b"
    )

    matches = list(pattern.finditer(text))

    if len(matches) <= 1:
        return text

    first = matches[0]
    second = matches[1]

    # İlk sınıfın gövdesini bul:
    # Bir sonraki top-level class veya def başlangıcına kadar.
    next_top = re.search(
        r"(?m)^(?:class\s+|def\s+|async\s+def\s+)",
        text[first.end():],
    )

    if next_top:
        end = first.end() + next_top.start()
    else:
        end = second.start()

    # Güvenlik:
    # İlk class bloğu ikinci class'tan önce bitmelidir.
    if end > second.start():
        end = second.start()

    removed = text[first.start():end]

    if not removed.strip():
        fail(
            "%s: duplicate class bulundu fakat kaldırılacak blok boş."
            % class_name
        )

    print(
        "[FIX] kernel.py: ilk duplicate class kaldırıldı: %s "
        "(%d byte)" % (class_name, len(removed))
    )

    return text[:first.start()] + text[end:]


def remove_first_duplicate_method_in_class(
    text: str,
    class_name: str,
    method_name: str,
) -> str:
    class_match = re.search(
        r"(?m)^class\s+" + re.escape(class_name) + r"\b",
        text,
    )

    if not class_match:
        fail(
            "%s.%s: sınıf bulunamadı."
            % (class_name, method_name)
        )

    next_class = re.search(
        r"(?m)^class\s+\w+",
        text[class_match.end():],
    )

    class_end = (
        class_match.end() + next_class.start()
        if next_class
        else len(text)
    )

    class_text = text[class_match.end():class_end]

    method_pattern = re.compile(
        r"(?m)^    def\s+" + re.escape(method_name) + r"\s*\("
    )

    methods = list(method_pattern.finditer(class_text))

    if len(methods) <= 1:
        return text

    first = methods[0]
    second = methods[1]

    # İlk method gövdesi ikinci method başlangıcına kadar.
    removed = class_text[first.start():second.start()]

    if not removed.strip():
        fail(
            "%s.%s: duplicate method bloğu boş."
            % (class_name, method_name)
        )

    print(
        "[FIX] kernel.py: ilk duplicate method kaldırıldı: %s.%s "
        "(%d byte)" %
        (class_name, method_name, len(removed))
    )

    new_class_text = (
        class_text[:first.start()]
        + class_text[second.start():]
    )

    return (
        text[:class_match.end()]
        + new_class_text
        + text[class_end:]
    )


def patch_alpha():
    path = ROOT / "alpha_core.py"
    text = path.read_text(encoding="utf-8")

    canonical_marker = (
        "# alpha_core.py — Honeycomb technical decision core."
    )

    text = remove_prefix_before_marker(
        text,
        canonical_marker,
        "alpha_core.py",
    )

    old_tmp = (
        '        alt = os.path.join("/tmp", '
        'os.path.basename(path) or "honeycomb_alpha.db")'
    )

    new_runtime = (
        '        runtime_dir = os.path.join(ROOT, ".honeycomb_runtime")\n'
        '        os.makedirs(runtime_dir, exist_ok=True)\n'
        '        alt = os.path.join(\n'
        '            runtime_dir,\n'
        '            os.path.basename(path) or "honeycomb_alpha.db",\n'
        '        )'
    )

    if old_tmp in text:
        text = text.replace(old_tmp, new_runtime, 1)
        print("[FIX] alpha_core.py: /tmp fallback kaldırıldı.")
    else:
        print("[OK] alpha_core.py: /tmp fallback exact block bulunmadı.")

    if "/tmp/" in text:
        print("[WARNING] alpha_core.py içinde hâlâ /tmp referansı mevcut.")
    else:
        print("[OK] alpha_core.py: /tmp yok.")

    write(path, text)


def patch_kernel():
    path = ROOT / "live" / "kernel.py"
    text = path.read_text(encoding="utf-8")

    # Merge sonucu oluşan ilk duplicate sınıflar.
    for cls in (
        "CircuitBreaker",
        "CryptographicAuditLedger",
        "PartialProfitEngine",
        "DynamicTrailingStopEngine",
    ):
        text = remove_first_duplicate_top_level_class(text, cls)

    # CryptographicAuditLedger içinde ilk bozuk/yarım
    # _last_hash -> append -> verify zincirini kaldır.
    text = remove_first_duplicate_method_in_class(
        text,
        "CryptographicAuditLedger",
        "_last_hash",
    )

    # Bilinen Python SyntaxWarning:
    # expanduser('~/.honeycomb') doğru formdur.
    text = text.replace(
        "os.path.expanduser('\\\\~/.honeycomb')",
        "os.path.expanduser('~/.honeycomb')",
    )

    write(path, text)


def patch_hardened_sign():
    path = ROOT / "live" / "kernel_hardened_sign.py"
    text = path.read_text(encoding="utf-8")

    pattern = re.compile(
        r"(?m)^def hardened_http\(\s*self,\s*method,\s*path,"
    )
    first = pattern.search(text)

    typed = re.search(
        r"(?m)^def hardened_http\(\s*$",
        text,
    )

    if first and typed and first.start() < typed.start():
        print("[FIX] kernel_hardened_sign.py: ilk eksik hardened_http kaldırıldı.")
        text = text[:first.start()] + text[typed.start():]
    else:
        print("[OK] kernel_hardened_sign.py: ilk duplicate signature yok.")

    duplicate_body = """        body = urllib.parse.urlencode(
            {str(k): str(v) for k, v in params.items() if v is not None}, doseq=True
        )

      url = self.v["rest"] + path + (("?" + body) if method.upper() == "GET" and body else "")
      data = body.encode("utf-8") if method.upper() != "GET" else None
      headers = {
          "X-MBX-APIKEY": self.key,
          "Content-Type": "application/x-www-form-urlencoded",
      }
"""

    # Gerçek dosyada girinti 4 boşluk olabilir.
    duplicate_body_alt = """      body = urllib.parse.urlencode(
              {str(k): str(v) for k, v in params.items() if v is not None}, doseq=True
          )

      url = self.v["rest"] + path + (("?" + body) if method.upper() == "GET" and body else "")
      data = body.encode("utf-8") if method.upper() != "GET" else None
      headers = {
          "X-MBX-APIKEY": self.key,
          "Content-Type": "application/x-www-form-urlencoded",
      }
"""

    if duplicate_body in text:
        text = text.replace(duplicate_body, "", 1)
        print("[FIX] kernel_hardened_sign.py: duplicate HTTP body bloğu kaldırıldı.")
    elif duplicate_body_alt in text:
        text = text.replace(duplicate_body_alt, "", 1)
        print("[FIX] kernel_hardened_sign.py: duplicate HTTP body bloğu kaldırıldı.")
    else:
        # Satır yapısı değişmişse ikinci url bloğunu yapısal olarak bul.
        urls = list(re.finditer(
            r'(?m)^    \s*url = self\.v\["rest"\] \+ path',
            text,
        ))

        if len(urls) >= 2:
            second_url = urls[1]

            body_start = text.rfind(
                "        body = urllib.parse.urlencode(",
                0,
                second_url.start(),
            )

            if body_start >= 0:
                # İkinci headers bloğunun kapanışından sonra sil.
                headers_end = text.find(
                    '        }\n',
                    second_url.start(),
                )

                if headers_end >= 0:
                    headers_end += len('        }\n')
                    text = (
                        text[:body_start]
                        + text[headers_end:]
                    )
                    print(
                        "[FIX] kernel_hardened_sign.py: "
                        "ikinci body/url/headers bloğu kaldırıldı."
                    )
                else:
                    fail(
                        "kernel_hardened_sign.py: duplicate HTTP "
                        "headers bloğu bulunamadı."
                    )
            else:
                fail(
                    "kernel_hardened_sign.py: duplicate HTTP body "
                    "başlangıcı bulunamadı."
                )
        else:
            print(
                "[OK] kernel_hardened_sign.py: duplicate URL bloğu yok."
            )

    write(path, text)


def patch_scanner():
    path = ROOT / "extreme_scanner_engine.py"
    text = path.read_text(encoding="utf-8")

    imports = list(re.finditer(
        r"(?m)^from live\.kernel import \($",
        text,
    ))

    canonical_account = text.find(
        'ACCOUNT_LABEL = os.getenv("ACCOUNT_LABEL", "SCANNER-OMEGA")'
    )

    if len(imports) >= 2 and canonical_account >= 0:
        start = imports[1].start()

        if start < canonical_account:
            text = text[:start] + text[canonical_account:]
            print(
                "[FIX] extreme_scanner_engine.py: "
                "duplicate import/env/config bloğu kaldırıldı."
            )
        else:
            print(
                "[OK] extreme_scanner_engine.py: duplicate orta blok "
                "yeri zaten doğru."
            )
    else:
        fail(
            "extreme_scanner_engine.py: beklenen ikinci "
            "live.kernel import bloğu veya canonical ACCOUNT_LABEL bulunamadı."
        )

    write(path, text)


def compile_target(path: Path) -> bool:
    proc = subprocess.run(
        [sys.executable, "-m", "py_compile", str(path)],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    if proc.returncode == 0:
        print("[PY_COMPILE OK] %s" % path.relative_to(ROOT))
        return True

    print("[PY_COMPILE FAIL] %s" % path.relative_to(ROOT))
    print(proc.stderr.rstrip())
    return False


def ast_check(path: Path) -> bool:
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except Exception as e:
        print("[AST FAIL] %s :: %s" % (path.relative_to(ROOT), e))
        return False

    classes = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            classes.setdefault(node.name, []).append(node.lineno)

    duplicate_classes = {
        name: lines
        for name, lines in classes.items()
        if len(lines) > 1
    }

    if duplicate_classes:
        print(
            "[AST FAIL] %s duplicate top-level classes: %s"
            % (path.relative_to(ROOT), duplicate_classes)
        )
        return False

    print("[AST OK] %s" % path.relative_to(ROOT))
    return True


def source_tmp_check(path: Path) -> bool:
    text = path.read_text(encoding="utf-8", errors="ignore")
    if "/tmp/" in text or '"/tmp"' in text or "'/tmp'" in text:
        print(
            "[TMP WARNING] %s içinde /tmp referansı var."
            % path.relative_to(ROOT)
        )
        return False

    print("[TMP OK] %s" % path.relative_to(ROOT))
    return True


def main():
    print("=" * 72)
    print(" HONEYCOMB — FINAL STRUCTURAL REPAIR")
    print(" NO /tmp | NO LIVE EXECUTION | BACKUP + ROLLBACK")
    print("=" * 72)

    if not (ROOT / ".git").exists():
        fail("Git repo kökü doğrulanamadı: %s" % ROOT)

    BACKUP_ROOT.mkdir(parents=True, exist_ok=True)

    backup_dir, records = backup_all()

    original_hashes = {
        path: digest for path, _backup, digest in records
    }

    try:
        patch_alpha()
        patch_kernel()
        patch_hardened_sign()
        patch_scanner()

        print("\n" + "=" * 72)
        print(" PYTHON SYNTAX VALIDATION")
        print("=" * 72)

        for path in TARGETS:
            if not compile_target(path):
                raise RuntimeError(
                    "py_compile başarısız: %s" % path
                )

        print("\n" + "=" * 72)
        print(" AST STRUCTURAL VALIDATION")
        print("=" * 72)

        for path in TARGETS:
            if not ast_check(path):
                raise RuntimeError(
                    "AST doğrulaması başarısız: %s" % path
                )

        print("\n" + "=" * 72)
        print(" /tmp VALIDATION")
        print("=" * 72)

        # alpha_core'da /tmp kesinlikle olmamalı.
        if not source_tmp_check(ROOT / "alpha_core.py"):
            raise RuntimeError(
                "alpha_core.py içinde /tmp kaldı."
            )

        print("\n" + "=" * 72)
        print(" FINAL HASH / CHANGE EVIDENCE")
        print("=" * 72)

        for path, _backup, old_hash in records:
            new_hash = sha256(path)
            if new_hash == old_hash:
                fail(
                    "Beklenen onarım değişikliği oluşmadı: %s"
                    % path.relative_to(ROOT)
                )

            print(
                "%s\n  OLD=%s\n  NEW=%s"
                % (
                    path.relative_to(ROOT),
                    old_hash,
                    new_hash,
                )
            )

        print("\n" + "=" * 72)
        print(" REPAIR SUCCESS")
        print("=" * 72)
        print("Backup : %s" % backup_dir.relative_to(ROOT))
        print("Files  : %d" % len(TARGETS))
        print("Live   : NOT STARTED")
        print("Orders : NOT SENT")
        print("Env    : NOT MODIFIED")
        print("DB     : NOT MODIFIED")
        print("Logs   : NOT MODIFIED")
        print("/tmp   : NOT USED")
        print("=" * 72)

    except Exception as e:
        print("\n[ERROR] %s" % e)
        restore(records)

        print("\n[ROLLBACK VERIFY]")
        for path, _backup, old_hash in records:
            current = sha256(path)
            if current != old_hash:
                print(
                    "[ROLLBACK FAIL] %s"
                    % path.relative_to(ROOT)
                )
                raise SystemExit(2)

            print(
                "[ROLLBACK OK] %s"
                % path.relative_to(ROOT)
            )

        raise SystemExit(1)


if __name__ == "__main__":
    main()
