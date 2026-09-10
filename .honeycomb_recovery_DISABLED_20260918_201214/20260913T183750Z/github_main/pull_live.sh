#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
ROOT="${1:-$HOME/honeycomb-execution-core}"
cd "$ROOT"
echo "REMOTE=$(git remote get-url origin 2>/dev/null || echo NONE)"
git fetch origin main
git checkout main
git pull --ff-only origin main || git pull origin main || true
echo "=== live/ after pull ==="
ls -la live/ 2>/dev/null || echo "NO live/ DIRECTORY"
echo "=== kernel check ==="
python3 -c "
from pathlib import Path
p = Path('live/kernel.py')
if not p.exists():
    print('MISSING live/kernel.py')
else:
    t = p.read_text()
    print('size', len(t))
    print('has LiveKernel', 'class LiveKernel' in t)
    print('has open_market', 'def open_market' in t)
"
echo "=== engines ==="
ls -la live/apex_usdt.py live/helix_coin.py live/maker_sniper.py live/desk.py live/net_shield.py 2>/dev/null || true
