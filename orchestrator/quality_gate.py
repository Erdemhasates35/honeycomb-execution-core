"""Deterministic repository quality certification for Honeycomb runtime components."""
from __future__ import annotations

import ast
import json
import re
import subprocess
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 2
CORE = {"orchestrator/control_plane.py", "nexus_testnet_bridge.py", "run_nexus_testnet.sh", "runtime/start_testnet.sh"}
SKIP_PARTS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}
SOURCE_EXT = {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".go", ".sh", ".bash"}
CHECKS = ("syntax", "typed", "error_boundary", "observability", "documentation", "validation", "security", "maintainability", "tests", "no_debt_markers")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _base_checks() -> dict[str, bool]:
    return {name: False for name in CHECKS}


def _python_checks(path: Path, text: str, root: Path) -> dict[str, bool]:
    checks = _base_checks()
    try:
        tree = ast.parse(text, filename=str(path))
        checks["syntax"] = True
        functions = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        checks["typed"] = not functions or sum(bool(getattr(n, "returns", None)) for n in functions) / len(functions) >= 0.7
        checks["error_boundary"] = any(isinstance(n, ast.Try) for n in ast.walk(tree))
        checks["observability"] = bool(re.search(r"\b(logging|logger)\b", text))
        checks["documentation"] = bool(ast.get_docstring(tree)) or '"""' in text
        checks["validation"] = any(isinstance(n, (ast.Assert, ast.Raise)) for n in ast.walk(tree)) or "Field(" in text
        checks["security"] = any(x in text.lower() for x in ("hmac", "redact", "secret", "api_key", "token"))
        checks["maintainability"] = len(text.splitlines()) < 2500 and "eval(" not in text and "exec(" not in text
        checks["tests"] = (root / "tests").exists() and (path.name.startswith("test_") or any((root / "tests").rglob(f"test_{path.stem}.py")))
        checks["no_debt_markers"] = not bool(re.search(r"\b(TODO|FIXME|XXX)\b", text, re.I))
    except SyntaxError:
        pass
    return checks


def _go_checks(path: Path, text: str, root: Path) -> dict[str, bool]:
    checks = _base_checks()
    checks["syntax"] = bool(re.search(r"(?m)^package\s+[A-Za-z_][A-Za-z0-9_]*", text))
    checks["typed"] = bool(re.search(r"(?m)^\s*(type|func|var|const)\b", text))
    checks["error_boundary"] = "error" in text and ("if err != nil" in text or "errors.New" in text)
    checks["observability"] = any(x in text for x in ("log.", "slog.", "zap.", "zerolog."))
    checks["documentation"] = bool(re.search(r"(?m)^//\s+[A-Z]", text))
    checks["validation"] = any(x in text for x in ("Validate(", "errors.New(", "fmt.Errorf("))
    checks["security"] = any(x in text.lower() for x in ("secret", "api_key", "hmac", "redact"))
    checks["maintainability"] = len(text.splitlines()) < 2500
    package_dir = path.parent
    checks["tests"] = any(package_dir.glob("*_test.go")) or path.name.endswith("_test.go")
    checks["no_debt_markers"] = not bool(re.search(r"\b(TODO|FIXME|XXX)\b", text, re.I))
    return checks


def _shell_checks(path: Path, text: str, root: Path) -> dict[str, bool]:
    checks = _base_checks()
    try:
        subprocess.run(["bash", "-n", str(path)], check=True, capture_output=True, text=True)
        checks["syntax"] = True
    except (OSError, subprocess.CalledProcessError):
        pass
    checks["typed"] = True
    checks["error_boundary"] = "set -Eeuo pipefail" in text or "set -e" in text
    checks["observability"] = "echo " in text or "tee " in text
    checks["documentation"] = text.startswith("#!") and "# " in text
    checks["validation"] = any(x in text for x in ("curl", "test ", "[ -", "command -v"))
    checks["security"] = "redact" in text.lower() or "127.0.0.1" in text or "set -a" in text
    checks["maintainability"] = len(text.splitlines()) < 1200
    checks["tests"] = (root / "tests").exists()
    checks["no_debt_markers"] = not bool(re.search(r"\b(TODO|FIXME|XXX)\b", text, re.I))
    return checks


def _generic_checks(path: Path, text: str, root: Path) -> dict[str, bool]:
    if path.suffix == ".py":
        return _python_checks(path, text, root)
    if path.suffix == ".go":
        return _go_checks(path, text, root)
    if path.suffix in {".sh", ".bash"}:
        return _shell_checks(path, text, root)
    checks = _base_checks()
    checks["syntax"] = True
    checks["typed"] = path.suffix not in {".ts", ".tsx"} or bool(re.search(r"(interface\s|type\s|:\s*(string|number|boolean|unknown|\w+\[\]))", text))
    checks["error_boundary"] = any(x in text for x in ("try", "catch", "Error"))
    checks["observability"] = any(x in text for x in ("logger", "logging", "console.error"))
    checks["documentation"] = any(x in text for x in ("/**", "README", "description"))
    checks["validation"] = any(x in text for x in ("validate", "schema", "zod", "Field"))
    checks["security"] = any(x in text.lower() for x in ("secret", "token", "api_key", "hmac"))
    checks["maintainability"] = len(text.splitlines()) < 3000
    checks["tests"] = (root / "tests").exists() and (path.name.endswith(".test.ts") or path.name.endswith(".test.tsx") or path.name.endswith(".spec.ts") or path.name.endswith(".spec.tsx"))
    checks["no_debt_markers"] = not bool(re.search(r"\b(TODO|FIXME|XXX)\b", text, re.I))
    return checks


def evaluate_file(path: Path, root: Path) -> dict[str, Any]:
    text = _read(path)
    checks = _generic_checks(path, text, root)
    score = round(10.0 * sum(checks.values()) / len(checks), 2)
    return {"path": path.relative_to(root).as_posix(), "score": score, "checks": checks, "failed_checks": [k for k, v in checks.items() if not v]}


def evaluate_repository(root: Path) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in SOURCE_EXT or any(part in SKIP_PARTS for part in path.parts):
            continue
        files.append(evaluate_file(path, root))
    core = [x for x in files if x["path"] in CORE]
    total = len(files)
    repository_score = round(sum(x["score"] for x in files) / total, 2) if total else 0.0
    return {"schema_version": SCHEMA_VERSION, "summary": {"total": total, "repository_score": repository_score, "core_9plus": len(core) == len(CORE) and all(x["score"] >= 9.0 for x in core), "core_count": len(core)}, "files": files}


def write_report(root: Path) -> dict[str, Any]:
    report = evaluate_repository(root)
    out = root / "reports" / "quality-gate.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report
