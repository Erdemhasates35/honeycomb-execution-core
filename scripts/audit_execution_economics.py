#!/usr/bin/env python3
"""Audit all engines for ambiguous economics and non-production execution paths."""
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
    "mock_execution": re.compile(r"MOCK_TX|mock.?tx|simulated.?profit|simulated.?pnl|paper.?execution", re.I),
    "random_signal": re.compile(r"np\.random|random\.uniform|random\.normalvariate", re.I),
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
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for number, line in enumerate(lines, 1):
            for name, pattern in PATTERNS.items():
                if pattern.search(line):
                    findings.append({"file": str(path.relative_to(ROOT)), "line": number, "kind": name, "snippet": line.strip()[:180]})
                    counts[name] += 1

    report = {
        "schema_version": 2,
        "repository": ROOT.name,
        "counts": counts,
        "findings": findings,
        "policy": {
            "fees": "explicit *_FEE_BPS only; legacy FEE_RATE must be normalized",
            "sizing": "risk-based; no fixed notional as primary sizing",
            "leverage": "dynamic and capped by validated config",
            "market_orders": "allowed only when expected net edge exceeds execution-cost penalty",
            "mock_execution": "never allowed on a LIVE execution path",
            "random_signal": "randomness may be used only in research/simulation, never as a production signal",
        },
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if counts["fee_literal_percent"] or counts["mock_execution"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
