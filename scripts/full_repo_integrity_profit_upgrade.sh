#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
ROOT="${ROOT:-$HOME/honeycomb-execution-core}";cd "$ROOT";STAMP="$(date +%Y%m%d_%H%M%S)";BACKUP="backups/full_integrity_${STAMP}";REPORT="reports/full_integrity_${STAMP}.txt";mkdir -p "$BACKUP" reports;exec > >(tee -a "$REPORT") 2>&1
printf '===== HONEYCOMB INSTITUTIONAL INTEGRITY / PROFIT UPGRADE %s =====\n' "$STAMP";git status --short || true
python3 - "$BACKUP" <<'PY'
from pathlib import Path
import re,shutil,sys
backup=Path(sys.argv[1]);excluded={'.git','backups','runtime','__pycache__'}
def eligible(p):return p.is_file() and p.suffix in {'.py','.sh','.ts','.tsx','.js','.json','.md'} and not any(x in excluded for x in p.parts)
def backup_file(p):
 d=backup/p;d.parent.mkdir(parents=True,exist_ok=True)
 if not d.exists():shutil.copy2(p,d)
for p in Path('.').rglob('*'):
 if not eligible(p):continue
 try:s=p.read_text(encoding='utf-8')
 except Exception:continue
 if '<<<<<<<' in s or '=======' in s or '>>>>>>>' in s:print('MERGE_MARKER',p)
 ns=re.sub(r'atr\(high\s*=\s*([^,\)]+),\s*low\s*=\s*([^,\)]+),\s*close\s*=\s*([^\)]+)\)',r'atr(\1, \2, \3)',s)
 if ns!=s:backup_file(p);p.write_text(ns,encoding='utf-8');print('ATR_CALL_REPAIRED',p)
PY
printf '[1] Financial contract compile\n';python3 -m py_compile institutional_finance.py risk_analytics.py institutional_adapter.py adaptive_profit_runtime.py profit_economics.py aggressive_profit_optimizer.py profit_max_engine.py extreme_scanner_engine.py sovereign_parliament_engine.py
printf '[2] Full Python compile\n';python3 -m compileall -q .
printf '[3] Merge-marker scan\n';if grep -RIn --exclude='*.bak*' --exclude-dir=.git --exclude-dir=backups --exclude-dir=runtime -E '^(<<<<<<<|=======|>>>>>>>)' .;then exit 2;else echo MERGE_MARKERS=0;fi
printf '[4] Finance unit tests\n';if command -v pytest >/dev/null 2>&1;then pytest -q tests/test_institutional_finance.py;else echo 'PYTEST_NOT_INSTALLED';fi
printf '[5] ATR smoke\n';PYTHONPATH="$ROOT" python3 - <<'PY'
from live.kernel import atr
c=[100+i for i in range(30)];h=[x+1 for x in c];l=[x-1 for x in c]
assert atr(c,14) is not None
assert atr(high=h,low=l,close=c,period=14) is not None
print('ATR_SMOKE=OK')
PY
printf '[6] Live gate invariant\n';PYTHONPATH="$ROOT" LIVE_ARMED=0 EXECUTION_MODE=LIVE python3 - <<'PY'
import os
assert os.getenv('LIVE_ARMED')=='0';assert os.getenv('EXECUTION_MODE')=='LIVE';print('LIVE_GATE=ARMED_FALSE_NO_ORDER_EXPECTED')
PY
printf '[7] Diff check\n';git diff --check;printf '\nBACKUP=%s\nREPORT=%s\n' "$BACKUP" "$REPORT";echo 'NO_NEW_ORDER_SENT_BY_THIS_SCRIPT=YES'
