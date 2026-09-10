cd ~/honeycomb-execution-core || exit 1

echo "=== 1. YEDEK ==="
cp live/kernel.py "live/kernel.py.bak.$(date +%s)"

echo "=== 2. GUARD FONKSİYONLARI ZATEN VAR MI KONTROL ==="
if grep -q "^def _finite_num" live/kernel.py; then
  echo "Zaten mevcut, dokunulmadı."
else
  cat >> live/kernel.py << 'EOF'


# ------------------------------------------------- NUMERIC GUARDS ---
# live/__init__.py bu isimleri bekliyordu ama kernel.py'de tanımlı değildi
# (ImportError: cannot import name '_finite_num'). None/nan/inf gelen
# fiyat, miktar, bakiye değerlerini scanner/alpha/parliament zincirine
# sızdırmadan güvenli karşılaştırma yapmak için eklendi.

import math as _math

def _finite_num(x, default=None):
    """None/NaN/Inf/geçersiz değerleri güvenli float'a çevirir; olmazsa default döner."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    if _math.isnan(v) or _math.isinf(v):
        return default
    return v

def _gt(a, b):
    a, b = _finite_num(a), _finite_num(b)
    if a is None or b is None:
        return False
    return a > b

def _lt(a, b):
    a, b = _finite_num(a), _finite_num(b)
    if a is None or b is None:
        return False
    return a < b

def _ge(a, b):
    a, b = _finite_num(a), _finite_num(b)
    if a is None or b is None:
        return False
    return a >= b

def _le(a, b):
    a, b = _finite_num(a), _finite_num(b)
    if a is None or b is None:
        return False
    return a <= b
EOF
  echo "Eklendi."
fi

echo
echo "=== 3. DERLEME KONTROLÜ ==="
python3 -m py_compile live/kernel.py && echo "PYCOMPILE_OK" || echo "PYCOMPILE_FAIL"

echo
echo "=== 4. IMPORT TESTİ ==="
python3 - << 'PY'
from live.kernel import _finite_num, _gt, _lt, _ge, _le
tests = [
    ("None", _finite_num(None)),
    ("nan", _finite_num(float("nan"))),
    ("valid", _finite_num(12.5)),
    ("gt_none", _gt(None, 10)),
    ("gt_valid", _gt(12, 10)),
    ("lt_valid", _lt(8, 10)),
    ("ge_valid", _ge(10, 10)),
    ("le_valid", _le(9, 10)),
]
for name, result in tests:
    print(f"{name}: {result}")
print("KERNEL_NUMERIC_GUARD=OK")
PY

echo
echo "=== 5. __init__.py TAM IMPORT TESTİ ==="
python3 -c "import live; print('LIVE_INIT_IMPORT_OK')"

echo
echo "=== 6. SOVEREIGN PARLIAMENT ENGINE IMPORT TESTİ (çalıştırmadan) ==="
python3 -c "
import ast
with open('sovereign_parliament_engine.py', encoding='utf-8') as f:
    src = f.read()
try:
    ast.parse(src)
    print('SOVEREIGN_PARLIAMENT_SYNTAX_OK')
except SyntaxError as e:
    print('SOVEREIGN_PARLIAMENT_SYNTAX_FAIL:', e)
"

echo
echo "============================================================"
echo " BİTTİ — yukarıda tüm adımlar OK ise şimdi motoru başlat:"
echo " python3 sovereign_parliament_engine.py"
echo "============================================================"
