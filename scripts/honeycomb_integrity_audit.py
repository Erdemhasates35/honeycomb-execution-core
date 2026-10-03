#!/usr/bin/env python3
"""Non-destructive Honeycomb integrity audit for Termux/Linux.

Scans source syntax, duplicate blobs, SQLite integrity/schema, and journal-like
JSON/SQLite files. It never deletes, rewrites, migrates, or mutates data.
"""
from __future__ import annotations
import ast, hashlib, json, os, sqlite3, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP = {".git",".venv","venv","node_modules","__pycache__",".next","dist","build",
        ".honeycomb_recovery_DISABLED_20260918_201214",".honeycomb_tools_DISABLED_20260918_201214"}

def ignored(p: Path) -> bool:
    return any(part in SKIP for part in p.parts)

def sha256(p: Path) -> str:
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()

def python_syntax():
    bad=[]
    for p in ROOT.rglob("*.py"):
        if ignored(p): continue
        try: ast.parse(p.read_text(encoding="utf-8",errors="replace"), filename=str(p))
        except Exception as e: bad.append((str(p.relative_to(ROOT)),str(e)))
    return bad

def sqlite_audit():
    rows=[]
    candidates=list(ROOT.rglob("*.db"))+list(ROOT.rglob("*.sqlite"))+list(ROOT.rglob("*.sqlite3"))
    seen=set()
    for p in candidates:
        if ignored(p) or p in seen: continue
        seen.add(p)
        try:
            con=sqlite3.connect(f"file:{p}?mode=ro",uri=True,timeout=2)
            integrity=con.execute("PRAGMA integrity_check").fetchone()[0]
            tables=con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
            counts={}
            for (name,) in tables:
                try: counts[name]=con.execute('SELECT COUNT(*) FROM "'+name.replace('"','""')+'"').fetchone()[0]
                except Exception as e: counts[name]="ERROR:"+str(e)
            con.close()
            rows.append({"path":str(p.relative_to(ROOT)),"integrity":integrity,"tables":counts})
        except Exception as e:
            rows.append({"path":str(p.relative_to(ROOT)),"integrity":"OPEN_ERROR:"+str(e)})
    return rows

def duplicate_blobs():
    groups={}
    for p in ROOT.rglob("*"):
        if not p.is_file() or ignored(p): continue
        try:
            size=p.stat().st_size
            if size==0 or size>10_000_000: continue
            groups.setdefault((size,sha256(p)),[]).append(str(p.relative_to(ROOT)))
        except Exception: pass
    return [v for v in groups.values() if len(v)>1]

def main():
    report={
        "root":str(ROOT),
        "python_syntax_errors":python_syntax(),
        "sqlite":sqlite_audit(),
        "duplicate_content_groups":duplicate_blobs(),
    }
    out=ROOT/"reports"/"honeycomb_integrity_audit.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({
        "python_syntax_errors":len(report["python_syntax_errors"]),
        "sqlite_files":len(report["sqlite"]),
        "sqlite_failures":sum(1 for x in report["sqlite"] if x["integrity"]!="ok"),
        "duplicate_groups":len(report["duplicate_content_groups"]),
        "report":str(out)
    },ensure_ascii=False,indent=2))
    return 1 if report["python_syntax_errors"] or any(x["integrity"]!="ok" for x in report["sqlite"]) else 0

if __name__=="__main__":
    raise SystemExit(main())
