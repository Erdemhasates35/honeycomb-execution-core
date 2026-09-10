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
git status --short || true

python3 - "$BACKUP" <<'PY'
from pathlib import Path
import re, shutil, sys, ast
backup=Path(sys.argv[1])
excluded={'.git','backups','runtime','__pycache__'}

def eligible(p):
    return p.is_file() and p.suffix in {'.py','.sh','.ts','.tsx','.js','.json','.md'} and not any(x in excluded for x in p.parts)

def backup_file(p):
    d=backup/p
    d.parent.mkdir(parents=True,exist_ok=True)
    if not d.exists(): shutil.copy2(p,d)

def repair_conflicts():
    for p in Path('.').rglob('*'):
        if not eligible(p): continue
        try: s=p.read_text(encoding='utf-8')
        except Exception: continue
        if '<<<<<<<' not in s: continue
        lines=s.splitlines(True); out=[]; i=0; changed=False; ambiguous=False
        while i<len(lines):
            if not lines[i].startswith('<<<<<<<'):
                out.append(lines[i]); i+=1; continue
            ours=[]; theirs=[]; side=0; i+=1; closed=False
            while i<len(lines):
                if lines[i].startswith('======='): side=1; i+=1; continue
                if lines[i].startswith('>>>>>>>'): closed=True; i+=1; break
                (theirs if side else ours).append(lines[i]); i+=1
            if not closed or (ours and theirs) or (not ours and not theirs):
                ambiguous=True; out.append('<<<<<<< CONFLICT_PRESERVED\n'); out.extend(ours); out.append('=======\n'); out.extend(theirs); out.append('>>>>>>> CONFLICT_PRESERVED\n'); continue
            out.extend(ours or theirs); changed=True
        if changed and not ambiguous:
            backup_file(p); p.write_text(''.join(out),encoding='utf-8'); print('CONFLICT_REPAIRED',p)
        elif ambiguous: print('CONFLICT_AMBIGUOUS',p)

repair_conflicts()

# Deterministic ATR call-site repair; kernel adapter is handled separately below.
for p in Path('.').rglob('*.py'):
    if not eligible(p): continue
    try: s=p.read_text(encoding='utf-8')
    except Exception: continue
    ns=re.sub(r'atr\(high\s*=\s*([^,\)]+),\s*low\s*=\s*([^,\)]+),\s*close\s*=\s*([^,\)]+)([^\)]*)\)',r'atr(\1, \2, \3\4)',s)
    if ns!=s:
        backup_file(p); p.write_text(ns,encoding='utf-8'); print('ATR_CALL_REPAIRED',p)

# Default leverage policy, never touch backups/runtime.
for p in Path('.').rglob('*.py'):
    if not eligible(p): continue
    try: s=p.read_text(encoding='utf-8')
    except Exception: continue
    ns=s
    ns=re.sub(r'(ENV\.get\("LEV_MIN"\)\s*or\s*")(?:10|20)("\))',r'\g<1>40\2',ns)
    ns=re.sub(r'(ENV\.get\("MAX_LEVERAGE"\)\s*or\s*")(?:20|25)("\))',r'\g<1>75\2',ns)
    if ns!=s:
        backup_file(p); p.write_text(ns,encoding='utf-8'); print('LEVERAGE_DEFAULTS_UPDATED',p)
PY

echo '[1] Kernel ATR adapter'
python3 - "$BACKUP" <<'PY'
from pathlib import Path
import re, shutil, sys
backup=Path(sys.argv[1]); p=Path('live/kernel.py')
if not p.exists(): print('KERNEL_NOT_PRESENT'); raise SystemExit
s=p.read_text(encoding='utf-8')
if 'def atr(closes=None, period=14, high=None, low=None, close=None' not in s:
    pat=r'def atr\(closes, period=14\):\n(?:    .*\n){1,8}?\n'
    m=re.search(pat,s)
    if m:
        d=backup/p; d.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(p,d)
        new='''def atr(closes=None, period=14, high=None, low=None, close=None, **_):\n    """ATR adapter for close-only and H/L/C callers; invalid data fails closed."""\n    series = close if close is not None else closes\n    try:\n        if series is None or len(series) < int(period)+1: return None\n        c=[float(x) for x in series]\n        if any(x != x for x in c): return None\n        if high is not None and low is not None:\n            h=[float(x) for x in high]; l=[float(x) for x in low]\n            if len(h)!=len(c) or len(l)!=len(c): return None\n            tr=[max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1])) for i in range(1,len(c))]\n            return sum(tr[-int(period):])/float(period)\n        tr=[abs(c[i]-c[i-1]) for i in range(1,len(c))]\n        return sum(tr[-int(period):])/float(period)\n    except (TypeError,ValueError,IndexError,ZeroDivisionError): return None\n\n'''
        p.write_text(s[:m.start()]+new+s[m.end():],encoding='utf-8'); print('KERNEL_ATR_UPDATED')
    else: print('KERNEL_ATR_PATTERN_NOT_FOUND')
else: print('KERNEL_ATR_ALREADY_OK')
PY

echo '[2] ENV policy (only if .env already exists)'
python3 - <<'PY'
from pathlib import Path
import re
p=Path('.env')
if p.exists():
 s=p.read_text(encoding='utf-8')
 for k,v in {'MARGIN_PCT':'0.05','CAPITAL_USE_PCT':'0.05','MIN_LEVERAGE':'40','LEV_MIN':'40','MAX_LEVERAGE':'75'}.items():
  if re.search(rf'^{re.escape(k)}=',s,re.M): s=re.sub(rf'^{re.escape(k)}=.*$',f'{k}={v}',s,flags=re.M)
  else: s+=f'\n{k}={v}'
 p.write_text(s,encoding='utf-8'); print('ENV_POLICY_UPDATED')
else: print('ENV_NOT_PRESENT_PRESERVED')
PY

echo '[3] Conflict scan'
if grep -RIn --exclude='*.bak*' --exclude-dir=.git --exclude-dir=backups --exclude-dir=runtime -E '^(<<<<<<<|=======|>>>>>>>)' .; then echo 'UNRESOLVED_CONFLICTS_REMAIN'; else echo 'MERGE_MARKERS=0'; fi

echo '[4] Python compile'
python3 -m compileall -q .

echo '[5] ATR smoke'
PYTHONPATH="$ROOT" python3 - <<'PY'
from live.kernel import atr
c=[100+i for i in range(30)]; h=[x+1 for x in c]; l=[x-1 for x in c]
assert atr(c,14) is not None
assert atr(high=h,low=l,close=c,period=14) is not None
print('ATR_SMOKE=OK')
PY

echo '[6] Diff check'
git diff --check || true
printf '\nBACKUP=%s\nREPORT=%s\n' "$BACKUP" "$REPORT"
echo 'NO_NEW_ORDER_SENT_BY_THIS_SCRIPT=YES'
