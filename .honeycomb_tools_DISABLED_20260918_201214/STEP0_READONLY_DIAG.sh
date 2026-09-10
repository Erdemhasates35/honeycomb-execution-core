#!/data/data/com.termux/files/usr/bin/bash
set +e

ROOT="$HOME/honeycomb-execution-core"

echo
echo "============================================================"
echo " HONEYCOMB STEP 0 — READ ONLY / DEĞİŞİKLİK YOK"
echo "============================================================"
echo "ROOT=$ROOT"
echo

cd "$ROOT" || exit 1

echo "---- GIT DURUMU ----"
git rev-parse --show-toplevel
git branch --show-current
git rev-parse HEAD
git rev-parse origin/main 2>/dev/null
git status --short
echo

echo "---- /tmp REFERANSLARI — TÜM REPO ----"
grep -RInE --exclude-dir=.git --exclude-dir=.venv \
  '(/tmp/|/tmp\b|honeycomb_sf\.lock)' . 2>/dev/null \
  | head -n 300
echo

echo "---- KERNEL LOCK TANIMLARI ----"
grep -nE 'class SingleFlight|honeycomb_sf|SingleFlight\(' \
  live/kernel.py live/kernel_hardened_sign.py \
  2>/dev/null
echo

echo "---- KERNEL EMİR FONKSİYONLARI ----"
grep -nE '^[[:space:]]*(async[[:space:]]+)?def[[:space:]]+' \
  live/kernel.py 2>/dev/null \
  | grep -Ei 'order|market|open|close|position|balance|mark|fill'
echo

echo "---- HELIX KERNEL ÇAĞRILARI ----"
grep -nE 'kernel\.(open_market|close_market|place_order|order|create_order|balance_usdt|mark)' \
  helix_sovereign_pro.py 2>/dev/null
echo

echo "---- LOBSTER KERNEL ÇAĞRILARI ----"
grep -RInE --exclude-dir=.git --exclude-dir=.venv \
  'kernel\.(open_market|close_market|place_order|order|create_order)|SingleFlight' \
  . 2>/dev/null \
  | grep -Ei 'lobster|aggressive|engine|kernel' \
  | head -n 200
echo

echo "---- PYTHON SYNTAX — SADECE KONTROL ----"
python3 -m py_compile \
  live/kernel.py \
  live/kernel_hardened_sign.py \
  helix_sovereign_pro.py \
  aggressive_live_engine.py \
  profit_aggressive_engine.py \
  2>&1
echo "PY_COMPILE_EXIT=$?"
echo

echo "---- IMPORT KONTROLÜ — LIVE EMİR YOK ----"
EXECUTION_MODE=PAPER \
EXECUTION=PAPER \
HONEYCOMB_MODE=PAPER \
LIVE_ARMED=0 \
python3 - <<'PY'
import inspect

print("IMPORT kernel...")
import live.kernel as k

print("LiveKernel:", k.LiveKernel)

names = [
    "open_market",
    "close_market",
    "place_order",
    "create_order",
    "order",
    "balance_usdt",
    "mark",
]

print("\nLiveKernel API:")
for name in names:
    obj = getattr(k.LiveKernel, name, None)
    print(f"{name:20} {'YES' if obj else 'NO'}",
          inspect.signature(obj) if obj else "")

print("\nSingleFlight:")
sf = getattr(k, "SingleFlight", None)
print(sf)
if sf:
    try:
        print("SingleFlight.__init__:",
              inspect.signature(sf.__init__))
    except Exception as e:
        print("signature error:", repr(e))

print("\nNO ORDER EXECUTION WAS PERFORMED.")
PY

echo
echo "============================================================"
echo " STEP 0 BİTTİ — DOSYALAR DEĞİŞTİRİLMEDİ"
echo "============================================================"
