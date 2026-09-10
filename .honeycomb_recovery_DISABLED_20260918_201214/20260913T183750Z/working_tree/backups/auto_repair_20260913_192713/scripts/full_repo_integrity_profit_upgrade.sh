#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

ROOT="${ROOT:-$HOME/honeycomb-execution-core}"
cd "$ROOT"
STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP="backups/full_integrity_${STAMP}"
REPORT="reports/full_integrity_${STAMP}.txt"
mkdir -p "$BACKUP" reports

exec > >(tee -a "$REPORT") 2>&1

echo "===== HONEYCOMB FULL INTEGRITY / PROFIT UPGRADE $STAMP ====="

echo "[0] Git state"
git status --short || true

backup_file() {
  local f="$1"
  [ -f "$f" ] || return 0
  mkdir -p "$BACKUP/$(dirname "$f")"
  cp -p "$f" "$BACKUP/$f"
}

# Only deterministic repairs are automated. Ambiguous conflict blocks are preserved and reported.
repair_conflicts() {
  python3 - "$BACKUP" <<'PY'
from pathlib import Path
import re, shutil, sys

backup = Path(sys.argv[1])
roots = [Path('.')]
excluded = {'.git', 'backups', 'runtime'}

for p in Path('.').rglob('*'):
    if not p.is_file() or p.suffix not in {'.py','.sh','.ts','.tsx','.js','.json','.md'}:
        continue
    if any(x in excluded for x in p.parts):
        continue
    try:
        s = p.read_text(encoding='utf-8')
    except Exception:
        continue
    if '<<<<<<<' not in s:
        continue

    blocks = []
    out=[]
    lines=s.splitlines(True)
    i=0
    changed=False
    ambiguous=False
    while i < len(lines):
        if not lines[i].startswith('<<<<<<<'):
            out.append(lines[i]); i+=1; continue
        start=i; i+=1; ours=[]; theirs=[]; section='ours'; marker_end=None
        while i < len(lines):
            if lines[i].startswith('======='):
                section='theirs'; i+=1; continue
            if lines[i].startswith('>>>>>>>'):
                marker_end=i; i+=1; break
            (ours if section=='ours' else theirs).append(lines[i]); i+=1
        if marker_end is None:
            ambiguous=True; break
        if ours and not theirs:
            out.extend(ours); changed=True
        elif theirs and not ours:
            out.extend(theirs); changed=True
        else:
            ambiguous=True
            out.extend(lines[start:marker_end+1])
    if changed and not ambiguous:
        dst=backup/p
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p,dst)
        p.write_text(''.join(out),encoding='utf-8')
        print(f'CONFLICT_REPAIRED {p}')
    elif ambiguous:
        print(f'CONFLICT_AMBIGUOUS {p}')

repair_conflicts()
PY
}

repair_conflicts

echo "[1] Kernel ATR adapter"
python3 - "$BACKUP" <<'PY'
from pathlib import Path
import shutil, sys
backup=Path(sys.argv[1])
p=Path('live/kernel.py')
if p.exists():
    s=p.read_text(encoding='utf-8')
    old='''def atr(closes, period=14):\n    if len(closes) < period + 1: return None\n    trs = [abs(closes[i] - closes[i - 1]) for i in range(1, len(closes))]\n    return sum(trs[-period:]) / period'''
    new='''def atr(closes=None, period=14, high=None, low=None, close=None, **_):\n    """ATR adapter: supports close-series and H/L/C callers without None/NaN crashes."""\n    series = close if close is not None else closes\n    try:\n        if series is None or len(series) < period + 1:\n            return None\n        c = [float(x) for x in series]\n        if high is not None and low is not None:\n            h = [float(x) for x in high]\n            l = [float(x) for x in low]\n            if len(h) != len(c) or len(l) != len(c):\n                return None\n            tr=[]\n            for i in range(1,len(c)):\n                tr.append(max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1])))\n            return sum(tr[-period:])/float(period)\n        tr=[abs(c[i]-c[i-1]) for i in range(1,len(c))]\n        return sum(tr[-period:])/float(period)\n    except (TypeError, ValueError, IndexError, ZeroDivisionError):\n        return None'''
    if old in s:
        dst=backup/p; dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(p,dst)
        p.write_text(s.replace(old,new),encoding='utf-8')
        print('KERNEL_ATR_UPDATED')
    else:
        print('KERNEL_ATR_ALREADY_UPDATED_OR_DIFFERENT')
PY

echo "[2] Remove deterministic broken keyword ATR call sites"
python3 - "$BACKUP" <<'PY'
from pathlib import Path
import re, shutil, sys
backup=Path(sys.argv[1])
for p in Path('.').rglob('*.py'):
    if any(x in {'backups','runtime','.git'} for x in p.parts): continue
    try: s=p.read_text(encoding='utf-8')
    except Exception: continue
    ns=re.sub(r'atr\(high\s*=\s*([^,\)]+),\s*low\s*=\s*([^,\)]+),\s*close\s*=\s*([^,\)]+)([^\)]*)\)', r'atr(\1, \2, \3\4)', s)
    if ns != s:
        dst=backup/p; dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(p,dst)
        p.write_text(ns,encoding='utf-8')
        print('ATR_CALL_REPAIRED',p)
PY

echo "[3] Dynamic leverage defaults: 40..75"
python3 - "$BACKUP" <<'PY'
from pathlib import Path
import re, shutil, sys
backup=Path(sys.argv[1])
patterns=[
 (r'(ENV\.get\("LEV_MIN"\)\s*or\s*")10("\))',r'\g<1>40\2'),
 (r'(ENV\.get\("MAX_LEVERAGE"\)\s*or\s*")25("\))',r'\g<1>75\2'),
 (r'(ENV\.get\("LEV_MIN"\)\s*or\s*")20("\))',r'\g<1>40\2'),
]
for p in Path('.').rglob('*.py'):
    if any(x in {'backups','runtime','.git'} for x in p.parts): continue
    try:s=p.read_text(encoding='utf-8')
    except Exception:continue
    ns=s
    for a,b in patterns: ns=re.sub(a,b,ns)
    if ns!=s:
        dst=backup/p; dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(p,dst); p.write_text(ns,encoding='utf-8'); print('LEVERAGE_DEFAULTS_UPDATED',p)
PY

echo "[4] 5% margin policy"
python3 - <<'PY'
from pathlib import Path
p=Path('.env')
if p.exists():
    s=p.read_text(encoding='utf-8')
    vals={'MARGIN_PCT':'0.05','CAPITAL_USE_PCT':'0.05','MIN_LEVERAGE':'40','LEV_MIN':'40','MAX_LEVERAGE':'75'}
    import re
    for k,v in vals.items():
        if re.search(rf'^{re.escape(k)}=',s,re.M): s=re.sub(rf'^{re.escape(k)}=.*$',f'{k}={v}',s,flags=re.M)
        else: s += f'\n{k}={v}'
    p.write_text(s,encoding='utf-8')
    print('ENV_MARGIN_LEVERAGE_UPDATED')
else:
    print('ENV_NOT_PRESENT_PRESERVED')
PY

echo "[5] Conflict check"
if grep -RIn --exclude='*.bak*' --exclude-dir=.git --exclude-dir=backups --exclude-dir=runtime -E '^(<<<<<<<|=======|>>>>>>>)' .; then
  echo 'UNRESOLVED_CONFLICTS_REMAIN'
else
  echo 'MERGE_MARKERS=0'
fi

echo "[6] Python compile"
python3 -m compileall -q . || { echo 'PYTHON_COMPILE_FAILED'; exit 21; }

echo "[7] Git whitespace"
git diff --check

echo "[8] ATR smoke test"
PYTHONPATH="$ROOT" python3 - <<'PY'
from live.kernel import atr
c=[100.0+i for i in range(30)]
h=[x+1 for x in c]
l=[x-1 for x in c]
assert atr(c,14) is not None
assert atr(high=h,low=l,close=c,period=14) is not None
print('ATR_SMOKE=OK')
PY

echo "[9] Final state"
git status --short
printf '\nBACKUP=%s\nREPORT=%s\n' "$BACKUP" "$REPORT"
echo "NO_NEW_ORDER_SENT_BY_THIS_SCRIPT=YES"
