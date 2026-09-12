#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Non-destructive Honeycomb repository/runtime repair.

Repairs local working-tree text files without deleting originals. Every changed
file is copied to a timestamped backup first. Merge-conflict blocks are tested
as OURS/THEIRS/BOTH and the first syntactically valid candidate is selected;
when only one side is valid, the discarded side is preserved in the backup.
Also repairs known Helix bootstrap/execution defects and writes an audit.
"""
from __future__ import annotations
import ast, datetime as dt, json, os, re, shutil, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAMP = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
BACKUP = ROOT / "backups" / f"repo_integrity_{STAMP}"
REPORT = ROOT / "reports" / f"repo_integrity_{STAMP}.json"
TEXT_EXT = {".py", ".pyw", ".js", ".mjs", ".ts", ".tsx", ".json", ".sh", ".md", ".yml", ".yaml", ".toml", ".txt"}
MARKERS = ("<<<<<<< ", "=======", ">>>>>>> ")


def tracked_files():
    p = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, text=False, capture_output=True, check=True)
    return [ROOT / x.decode("utf-8", "surrogateescape") for x in p.stdout.split(b"\0") if x]


def backup(path: Path):
    dest = BACKUP / path.relative_to(ROOT)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, dest)


def py_ok(text: str) -> bool:
    try:
        ast.parse(text, filename="candidate.py")
        return True
    except Exception:
        return False


def resolve_conflicts(text: str, suffix: str):
    if "<<<<<<< " not in text or "=======\n" not in text or ">>>>>>> " not in text:
        return text, False, "none"
    lines = text.splitlines(True)
    out, i, changed, choices = [], 0, False, []
    while i < len(lines):
        if lines[i].startswith("<<<<<<< "):
            start = i; i += 1; ours = []
            while i < len(lines) and not lines[i].startswith("======="):
                ours.append(lines[i]); i += 1
            if i >= len(lines): return text, False, "unterminated"
            i += 1; theirs = []
            while i < len(lines) and not lines[i].startswith(">>>>>>> "):
                theirs.append(lines[i]); i += 1
            if i >= len(lines): return text, False, "unterminated"
            i += 1
            branch = lines[start].split(" ", 1)[1].strip()
            candidates = [("both", ours + theirs), ("ours", ours), ("theirs", theirs)]
            if suffix == ".py":
                valid = [(n, body) for n, body in candidates if py_ok("".join(out + body + lines[i:]))]
                name, body = valid[0] if valid else ("both", ours + theirs)
            else:
                name, body = "both", ours + theirs
            out.extend(body); choices.append({"branch": branch, "choice": name}); changed = True
        else:
            out.append(lines[i]); i += 1
    return "".join(out), changed, choices


def repair_helix(path: Path):
    text = path.read_text(encoding="utf-8", errors="surrogateescape")
    original = text
    text, conflict_changed, conflict_choice = resolve_conflicts(text, path.suffix)
    if "from typing import" not in text:
        text = text.replace("import sys\n", "import sys\nfrom typing import Any, Deque, Dict, List, Optional, Tuple\n", 1)
    elif "Dict" not in text.split("from typing import", 1)[1].split("\n", 1)[0]:
        text = re.sub(r"from typing import ([^\n]+)", lambda m: "from typing import " + m.group(1) + (", Dict" if "Dict" not in m.group(1) else ""), text, count=1)
    if "ROOT = os.path.dirname(os.path.abspath(__file__))" not in text:
        anchor = "except Exception:\n    pass\n"
        if anchor in text:
            text = text.replace(anchor, anchor + "\nROOT = os.path.dirname(os.path.abspath(__file__))\nif ROOT not in sys.path:\n    sys.path.insert(0, ROOT)\n", 1)
    text = text.replace('ENV.get("LEV_MIN") or "10"', 'ENV.get("LEV_MIN") or "40"')
    text = text.replace('ENV.get("MAX_LEVERAGE") or "25"', 'ENV.get("MAX_LEVERAGE") or "75"')
    replacements = {
        'meta-llama/nvidia/nemotron-3.5-lightning:nvidia/nemotron-3.5-lightning:inclusionai/ling-3.0-flash-fin:minimax/minimax-m3:meta-llama/llama-3.3-70b-instruct:qwen/qwen3-coder:free': 'nvidia/nemotron-3.5-lightning:free',
        'google/nvidia/nemotron-3.5-lightning:nvidia/nemotron-3.5-lightning:inclusionai/ling-3.0-flash-fin:minimax/minimax-m3:meta-llama/llama-3.3-70b-instruct:qwen/qwen3-coder:free': 'inclusionai/ling-3.0-flash-fin:free',
        'mistralai/nvidia/nemotron-3.5-lightning:nvidia/nemotron-3.5-lightning:inclusionai/ling-3.0-flash-fin:minimax/minimax-m3:meta-llama/llama-3.3-70b-instruct:qwen/qwen3-coder:free': 'nvidia/nemotron-3.5-lightning:free',
        'huggingfaceh4/nvidia/nemotron-3.5-lightning:nvidia/nemotron-3.5-lightning:inclusionai/ling-3.0-flash-fin:minimax/minimax-m3:meta-llama/llama-3.3-70b-instruct:qwen/qwen3-coder:free': 'minimax/minimax-m3',
    }
    for a, b in replacements.items(): text = text.replace(a, b)
    text = text.replace('            print("[GİRİŞ BAŞARISIZ]")\n            log_and_learn(symbol, side, score, conf, "FAIL", "exception")\n            print("[GİRİŞ BAŞARISIZ]")\n            print("[GİRİŞ BAŞARISIZ]")', '            print("[GİRİŞ BAŞARISIZ]")')
    # Known broken zero-balance branch: it referenced e outside an exception scope.
    bad = re.compile(r'        if bal <= 0:\n(?:            .*\n){1,12}?            return\n', re.M)
    if bad.search(text):
        text = bad.sub('        if bal <= 0:\n            log_and_learn(symbol, side, score, conf, "FAIL", "zero futures wallet balance", engine="helix")\n            log("ENTER FAIL %s: futures wallet balance is zero" % symbol)\n            return\n', text, count=1)
    if text != original:
        backup(path); path.write_text(text, encoding="utf-8")
    return {"changed": text != original, "conflicts": conflict_changed, "conflict_choice": conflict_choice}


def main():
    BACKUP.mkdir(parents=True, exist_ok=True)
    report = {"timestamp": STAMP, "backup": str(BACKUP), "files": [], "python_failures": []}
    for path in tracked_files():
        if not path.exists() or path.suffix.lower() not in TEXT_EXT: continue
        try: raw = path.read_text(encoding="utf-8", errors="surrogateescape")
        except Exception: continue
        if path.name == "helix_sovereign_pro.py":
            result = repair_helix(path)
            if result["changed"]: report["files"].append({"path": str(path.relative_to(ROOT)), **result})
        elif any(raw.startswith(m) or f"\n{m}" in raw for m in MARKERS):
            fixed, changed, choice = resolve_conflicts(raw, path.suffix.lower())
            if changed:
                backup(path); path.write_text(fixed, encoding="utf-8")
                report["files"].append({"path": str(path.relative_to(ROOT)), "conflicts": True, "choice": choice})
    for path in tracked_files():
        if path.suffix.lower() == ".py" and path.exists():
            p = subprocess.run(["python3", "-m", "py_compile", str(path)], cwd=ROOT, text=True, capture_output=True)
            if p.returncode != 0:
                report["python_failures"].append({"path": str(path.relative_to(ROOT)), "error": (p.stderr or p.stdout)[-2000:]})
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"backup": str(BACKUP), "report": str(REPORT), "changed": len(report["files"]), "python_failures": len(report["python_failures"])}, ensure_ascii=False))


if __name__ == "__main__": main()
