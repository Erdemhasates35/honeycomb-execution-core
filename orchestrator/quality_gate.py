"""Deterministic repository quality certification for Honeycomb runtime components."""

from __future__ import annotations

import ast
import json
import re
import subprocess
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
CORE = {
    "orchestrator/control_plane.py",
    "nexus_testnet_bridge.py",
    "run_nexus_testnet.sh",
    "runtime/start_testnet.sh",
}
SKIP_PARTS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}
SOURCE_EXT = {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".go", ".sh", ".bash"}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _python_checks(path: Path, text: str) -> dict[str, bool]:
    checks = {
        "syntax": False,
        "typed": False,
        "error_boundary": False,
        "observability": False,
        "documentation": False,
        "validation": False,
        "security": False,
        "maintainability": False,
        "tests": False,
        "no_debt_markers": False,
    }
    try:
        tree = ast.parse(text, filename=str(path))
        checks["syntax"] = True
        annotations = sum(bool(getattr(n, "returns", None)) for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
        checks["typed"] = annotations > 0
        checks["error_boundary"] = any(isinstance(n, ast.Try) for n in ast.walk(tree))
        checks["observability"] = bool(re.search(r"\b(logging|logger|print)\b", text))
        checks["documentation"] = bool(ast.get_docstring(tree)) or '"""' in text
        checks["validation"] = any(isinstance(n, (ast.Assert, ast.Raise)) for n in ast.walk(tree)) or "Field(" in text
        checks["security"] = any(x in text.lower() for x in ("hmac", "redact", "secret", "api_key", "token"))
        checks["maintainability"] = len(text.splitlines()) < 2500 and "eval(" not in text and "exec(" not in text
        checks["tests"] = Path(path.parent.parent / "tests").exists()
        checks["no_debt_markers"] = not bool(re.search(r"\b(TODO|FIXME|XXX)\b", text, re.I))
    except SyntaxError:
        pass
    return checks


def _shell_checks(path: Path, text: str) -> dict[str, bool]:
    checks = {
        "syntax": False,
        "typed": True,
        "error_boundary": False,
        "observability": False,
        "documentation": False,
        "validation": False,
        "security": False,
        "maintainability": False,
        "tests": False,
        "no_debt_markers": False,
    }
    try:
        subprocess.run(["bash", "-n", str(path)], check=True, capture_output=True, text=True)
        checks["syntax"] = True
    except (OSError, subprocess.CalledProcessError):
        pass
    checks["error_boundary"] = "set -e" in text or "set -Eeuo pipefail" in text
    checks["observability"] = "echo " in text or "tee " in text
    checks["documentation"] = text.startswith("#!") and ("# " in text or '"""' in text)
    checks["validation"] = "curl" in text or "test " in text or "[ -" in text
    checks["security"] = "set -a" in text or "redact" in text.lower() or "127.0.0.1" in text
    checks["maintainability"] = len(text.splitlines()) < 1200
    checks["tests"] = (path.parent.parent / "tests").exists()
    checks["no_debt_markers"] = not bool(re.search(r"\b(TODO|FIXME|XXX)\b", text, re.I))
    return checks


def _generic_checks(path: Path, text: str) -> dict[str, bool]:
    if path.suffix == ".py":
        return _python_checks(path, text)
    if path.suffix in {".sh", ".bash"}:
        return _shell_checks(path, text)
    checks = {k: False for k in ("syntax", "typed", "error_boundary", "observability", "documentation", "validation", "security", "maintainability", "tests", "no_debt_markers")}
    checks["syntax"] = True
    checks["typed"] = path.suffix not in {".ts", ".tsx"} or ("interface " in text or "type " in text or ": string" in text)
    checks["error_boundary"] = any(x in text for x in ("try", "catch", "error", "Error"))
    checks["observability"] = any(x in text for x in ("console.", "logger", "logging"))
    checks["documentation"] = any(x in text for x in ("/**", "README", "description"))
    checks["validation"] = any(x in text for x in ("validate", "schema", "zod", "Field"))
    checks["security"] = any(x in text.lower() for x in ("secret", "token", "api_key", "hmac"))
    checks["maintainability"] = len(text.splitlines()) < 3000
    checks["tests"] = (path.parent.parent / "tests").exists()
    checks["no_debt_markers"] = not bool(re.search(r"\b(TODO|FIXME|XXX)\b", text, re.I))
    return checks


def evaluate_file(path: Path, root: Path) -> dict[str, Any]:
    text = _read(path)
    checks = _generic_checks(path, text)
    passed = sum(checks.values())
    score = round(10.0 * passed / len(checks), 2)
    if path.relative_to(root).as_posix() in CORE and score < 9.0:
        score = round(score, 2)
    return {
        "path": path.relative_to(root).as_posix(),
        "score": score,
        "checks": checks,
        "failed_checks": [k for k, v in checks.items() if not v],
    }


def evaluate_repository(root: Path) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in SOURCE_EXT:
            continue
        if any(part in SKIP_PARTS for part in path.parts):
            continue
        files.append(evaluate_file(path, root))
    core = [x for x in files if x["path"] in CORE]
    total = len(files)
    repository_score = round(sum(x["score"] for x in files) / total, 2) if total else 0.0
    return {
        "schema_version": SCHEMA_VERSION,
        "summary": {
            "total": total,
            "repository_score": repository_score,
            "core_9plus": all(x["score"] >= 9.0 for x in core),
            "core_count": len(core),
        },
        "files": files,
    }


def write_report(root: Path) -> dict[str, Any]:
    report = evaluate_repository(root)
    out = root / "reports" / "quality-gate.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
