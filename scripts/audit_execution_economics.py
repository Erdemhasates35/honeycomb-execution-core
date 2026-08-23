#!/usr/bin/env python3
"""Audit all engines for ambiguous fees, hardcoded leverage and unsafe sizing patterns."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXTS = {".py", ".ts", ".tsx", ".js", ".sh", ".json"}
SKIP = {".git", ".venv", "node_modules", "__pycache__"}
PATTERNS = {
    "legacy_fee_rate": re.compile(r"\bFEE_RATE\b"),
    "fee_literal_percent": re.compile(r"(?:fee|commission)[^\n]{0,80}(?:0\.0?4|0\.05|4\s*%)", re.I),
    "hardcoded_leverage": re.compile(r"(?:leverage|LEV(?:ERAGE)?)[^\n]{0,50}(?:20|50|75)\s*[xX]?", re.I),
    "fixed_notional": re.compile(r"(?:notional|position.?size)[^\n]{0,60}(?:200|500|1000|5000)", re.I),
    "market_order": re.compile(r"(?:MARKET|market).*order|order.*(?:MARKET|market)", re.I),
}


def iter_files():
    for p in ROOT.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in EXTS:
            continue
        if any(part in SKIP for part in p.parts):
            continue
        yield p


def main():
    findings = []
    counts = {k: 0 for k in PATTERNS}
    for path in iter_files():
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for name, pattern in PATTERNS.items():
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                snippet = text.splitlines()[line - 1].strip()[:180]
                findings.append({"file": str(path.relative_to(ROOT)), "line": line, "kind": name, "snippet": snippet})
                counts[name] += 1

    report = {
        "schema_version": 1,
        "repository": ROOT.name,
        "counts": counts,
        "findings": findings,
        "policy": {
            "fees": "explicit *_FEE_BPS only; legacy FEE_RATE must be normalized",
            "sizing": "risk-based; no fixed notional as primary sizing",
            "leverage": "dynamic and capped by validated config",
            "market_orders": "allowed only when expected net edge exceeds execution-cost penalty",
        },
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    # CI-friendly: legacy fee use is a warning, but raw hardcoded cost semantics fail the audit.
    raise SystemExit(2 if counts["fee_literal_percent"] else 0)


if __name__ == "__main__":
    main()
